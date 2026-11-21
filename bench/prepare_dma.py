"""Build a plain x86-64 guest initramfs with an 8 MiB file-backed fw_cfg DMA check."""
import argparse
import gzip
import importlib.util
from pathlib import Path
import stat
import struct
import subprocess
import tempfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-init", type=Path, required=True, help="benchmark make_initramfs.py")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    spec = importlib.util.spec_from_file_location("base_init", args.base_init)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    output = args.output
    output.mkdir(exist_ok=True, parents=True)
    code = (Path(__file__).parent / "fw_cfg_probe.c").read_text() + base.INIT.replace(
        "    struct sysinfo info;", "    if (fw_cfg_probe()) for (;;) pause();\n    struct sysinfo info;")
    with tempfile.TemporaryDirectory() as tmp:
        binary = Path(tmp) / "init"
        subprocess.run(["gcc", "-static", "-O2", "-s", "-Wall", "-Wextra", "-Werror", "-Wl,--build-id=none",
                        "-D_GNU_SOURCE", "-x", "c", "-", "-o", str(binary)],
                       input=code.replace("#define _GNU_SOURCE", ""), text=True, check=True)
        entries = [(n, stat.S_IFDIR | 0o755) for n in ("dev", "proc", "sys")]
        entries += [("dev/console", stat.S_IFCHR | 0o600, b"", (5, 1)),
                    ("init", stat.S_IFREG | 0o755, binary.read_bytes()), ("TRAILER!!!", 0)]
        archive = b"".join(base.newc_entry(i, *e) for i, e in enumerate(entries, 1))
        (output / "initramfs.gz").write_bytes(gzip.compress(archive, compresslevel=1, mtime=0))
    with (output / "fixture.bin").open("wb") as file:
        patterns = [bytes((i + p) & 255 for i in range(4, 4096)) for p in range(256)]
        for p in range(2048):
            file.write(struct.pack("<I", p) + patterns[p & 255])


if __name__ == "__main__":
    main()
