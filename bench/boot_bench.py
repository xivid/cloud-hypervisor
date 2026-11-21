#!/usr/bin/env python3
"""Compare two Cloud Hypervisor builds from process start to a validated Linux PID 1 serial marker."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import statistics
import subprocess
import time

READY = re.compile(rb"(?:^|[\r\n])CH_BENCH_READY cpus=(\d+) mem_kib=(\d+) snp=([01])\r?\n")

def boot(args, variant, pair):
    tag = f"{pair:03d}-{variant}"
    serial = args.output / (tag + ".serial")
    log = args.output / (tag + ".log")
    serial.touch(exist_ok=False)
    command = [str(getattr(args, variant)), "--cpus", f"boot={args.cpus}",
               "--memory", f"size={args.memory_gib}G", "--serial", f"file={serial}",
               "--console", "off", "--kernel", str(args.kernel), "--initramfs", str(args.initramfs),
               "--cmdline", "console=ttyS0,115200 quiet panic=-1 rdinit=/init"]
    if args.igvm:
        command += ["--platform", "sev_snp=on", "--igvm", str(args.igvm),
                    "--fw-cfg-config", "kernel=on,initramfs=on,cmdline=on"]
    if args.firmware:
        command += ["--firmware", str(args.firmware), "--fw-cfg-config", "kernel=on,initramfs=on,cmdline=on"]
    with log.open("wb") as diagnostics, serial.open("rb") as monitor:
        t0 = time.monotonic_ns()
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=diagnostics, stderr=diagnostics)
        previous = b""
        try:
            while True:
                block = monitor.read()
                if block:
                    data = previous + block
                    match = READY.search(data)
                    detected = time.monotonic_ns()
                    if match:
                        cpus, mem_kib, snp = map(int, match.groups())
                        configured = args.memory_gib * 1024 * 1024
                        if cpus != args.cpus or snp != bool(args.igvm) or not configured * 0.8 <= mem_kib <= configured:
                            raise RuntimeError(f"{tag} guest configuration mismatch: {match.group()!r}")
                        return (detected - t0) / 1e6, cpus, mem_kib, snp
                    previous = data[-256:]
                if child.poll() is not None or time.monotonic_ns() - t0 >= args.timeout * 1e9:
                    raise RuntimeError(f"{tag} guest did not signal readiness (exit={child.poll()}); see {log} and {serial}")
                time.sleep(0.001)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("baseline", "candidate", "kernel", "initramfs"):
        parser.add_argument("--" + field, type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--igvm", type=Path, help="6-vCPU-compatible SNP stage0 for the default config")
    group.add_argument("--firmware", type=Path, help="firmware which can boot a kernel from fw_cfg")
    parser.add_argument("--output", type=Path, required=True, help="new results directory")
    parser.add_argument("--cpus", type=int, default=6)
    parser.add_argument("--memory-gib", type=int, default=8)
    parser.add_argument("--pairs", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if min(args.cpus, args.memory_gib, args.pairs, args.timeout) <= 0:
        parser.error("numeric options must be positive")
    inputs = {}
    for name in ("baseline", "candidate", "kernel", "initramfs", "igvm", "firmware"):
        path = getattr(args, name)
        if path:
            path = path.resolve(strict=True)
            setattr(args, name, path)
            with path.open("rb") as file:
                inputs[name] = {"path": str(path), "sha256": hashlib.file_digest(file, "sha256").hexdigest()}
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    meta = {"host": platform.uname()._asdict(), "cpus": args.cpus, "memory_gib": args.memory_gib,
            "pairs": args.pairs, "inputs": inputs, "timeout_s": args.timeout}
    with (args.output / "manifest.json").open("x") as file:
        json.dump(meta, file, indent=2)
    samples = {"baseline": [], "candidate": []}
    with (args.output / "runs.csv").open("x", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["pair", "position", "variant", "process_to_pid1_ms", "guest_cpus", "guest_mem_kib", "guest_snp"])
        for pair in range(args.pairs + 1):
            order = ("baseline", "candidate") if pair % 2 else ("candidate", "baseline")
            for pos, variant in enumerate(order, 1):
                duration, *guest = boot(args, variant, pair)
                writer.writerow([pair, pos, variant, duration, *guest])
                file.flush()
                if pair:
                    samples[variant].append(duration)
    summary = {variant: {"median_ms": statistics.median(values),
                         "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1]}
               for variant, values in samples.items()}
    summary["median_paired_saving_ms"] = statistics.median(b - c for b, c in zip(*samples.values()))
    result = json.dumps(summary, indent=2)
    (args.output / "summary.json").write_text(result + "\n")
    print(result)

if __name__ == "__main__":
    main()
