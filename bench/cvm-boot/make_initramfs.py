#!/usr/bin/env python3
"""Build a deterministic newc archive containing a static readiness probe for x86-64 Linux."""
import argparse
import gzip
from pathlib import Path
import stat
import subprocess
import tempfile

INIT = r"""
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/klog.h>
#include <sys/mount.h>
#include <sys/sysinfo.h>
#include <unistd.h>

int main(void) {
    if (mount("proc", "/proc", "proc", 0, NULL) || mount("sysfs", "/sys", "sysfs", 0, NULL))
        return 1;
    struct sysinfo info;
    if (sysinfo(&info)) return 2;
    int bytes = klogctl(10, NULL, 0);
    char *log = bytes > 0 ? calloc(1, (size_t) bytes + 1) : NULL;
    if (log && klogctl(3, log, bytes) < 0) return 3;
    int snp = 0;
    for (char *line = log ? strtok(log, "\n") : NULL; line; line = strtok(NULL, "\n")) {
        if (strstr(line, "Memory Encryption Features active:") && strstr(line, "SEV-SNP")) snp = 1;
    }
    printf("CH_BENCH_READY cpus=%ld mem_kib=%llu snp=%d\n", sysconf(_SC_NPROCESSORS_ONLN),
           (unsigned long long)info.totalram * info.mem_unit / 1024, snp);
    fflush(stdout);
    for (;;) pause();
}
"""

def newc_entry(number, name, mode, data=b"", rdev=(0, 0)):
    def pad(value):
        return value + bytes((-len(value)) % 4)
    name = name.encode() + b"\0"
    fields = [number, mode, 0, 0, 1, 0, len(data), 0, 0, *rdev, len(name), 0]
    header = b"070701" + b"".join(f"{value:08x}".encode() for value in fields)
    return pad(header + name) + pad(data)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pad-mib", type=int, default=0,
                        help="add reproducible incompressible data to exercise larger fw_cfg initrd reads")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        binary = Path(tmp) / "init"
        subprocess.run(["gcc", "-O2", "-static", "-s", "-Wl,--build-id=none",
                        "-x", "c", "-", "-o", str(binary)], input=INIT, text=True, check=True)
        entries = [(name, stat.S_IFDIR | 0o755) for name in ("dev", "proc", "sys")]
        entries += [("dev/console", stat.S_IFCHR | 0o600, b"", (5, 1)),
                    ("init", stat.S_IFREG | 0o755, binary.read_bytes())]
        if args.pad_mib:
            import random
            entries.append(("fixture.bin", stat.S_IFREG | 0o444,
                            random.Random(42).randbytes(args.pad_mib << 20)))
        entries.append(("TRAILER!!!", 0))
        archive = b"".join(newc_entry(i, *entry) for i, entry in enumerate(entries, 1))
        args.output.write_bytes(gzip.compress(archive, compresslevel=1, mtime=0))

if __name__ == "__main__":
    main()
