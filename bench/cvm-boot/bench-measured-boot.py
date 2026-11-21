#!/usr/bin/env python3
"""Compare the production measured-boot hash block builders with warm host caches."""
import argparse
import csv
import hashlib
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import tomllib

p = argparse.ArgumentParser()
p.add_argument('before', type=Path, help='baseline Cloud Hypervisor source tree')
p.add_argument('after', type=Path, help='candidate Cloud Hypervisor source tree')
p.add_argument('bzimage', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--pairs', type=int, default=31)
p.add_argument('--initrd', type=Path, help='also include this bootable initramfs')
p.add_argument('--build-only', action='store_true')
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
def write_changed(path, data):
    if not path.exists() or path.read_text() != data:
        path.write_text(data)

work = args.output / 'hash-build'
(work / 'src/bin').mkdir(parents=True, exist_ok=True)
lock = tomllib.loads((args.before / 'Cargo.lock').read_text())
deps = {item['name']: item['version'] for item in lock['package']}
manifest = ['[package]', 'name = "measure-hash"', 'version = "0.0.1"', 'edition = "2024"',
            '[profile.release]', 'opt-level = "s"', 'codegen-units = 1', 'lto = true', '[dependencies]']
for name, features in {'libc': [], 'linux-loader': ['bzimage'], 'sha2': [], 'uuid': [], 'vm-memory': [],
                       'vmm-sys-util': [], 'zerocopy': ['derive']}.items():
    feat = ', '.join(f'"{feature}"' for feature in features)
    manifest.append(f'{name} = {{ version = "={deps[name]}", default-features = false, features = [{feat}] }}')
write_changed(work / 'Cargo.toml', '\n'.join(manifest) + '\n')
main = '''
fn main() {
    let mut args = std::env::args().skip(1);
    let info = MeasuredBootInfo {
        kernel: File::open(args.next().unwrap()).unwrap(),
        initramfs: args.next().map(|path| File::open(path).unwrap()),
        cmdline: CString::new("console=ttyS0").unwrap(),
    };
    let start = std::time::Instant::now();
    let hash_block = info.build_hash_block().unwrap();
    let ns = start.elapsed().as_nanos();
    println!("{ns} {:?}", &hash_block[..]);
}
'''
for label, checkout in [('before', args.before), ('after', args.after)]:
    source = (checkout / 'vmm/src/sev.rs').read_text().split('/// SEV-SNP RMP/PSC minimum')[0]
    omit = ['use hypervisor::', 'use log::', 'use vm_device::', 'use crate::', 'use std::sync::']
    production = '\n'.join(line for line in source.splitlines() if not any(line.startswith(prefix) for prefix in omit))
    write_changed(work / f'src/bin/{label}.rs', production + '\n' + main)

target = work / 'target'
subprocess.run(['cargo', 'build', '--release', '--manifest-path', str(work / 'Cargo.toml')],
               env={**os.environ, 'CARGO_TARGET_DIR': str(target)}, check=True)
if args.build_only:
    raise SystemExit()

with tempfile.TemporaryDirectory() as tmpdir, (args.output / 'measured-boot.csv').open('w') as result:
    initrd = Path(tmpdir) / 'synthetic-initrd'
    initrd.write_bytes(bytes(range(256)) * 131072)
    output = csv.writer(result)
    output.writerow(['initrd_bytes','pair','position','variant','elapsed_ns','hash_block_sha256'])
    cases = [[args.bzimage], [args.bzimage, initrd]]
    if args.initrd is not None:
        cases.append([args.bzimage, args.initrd])
    for inputs in cases:
        ns = {'before': [], 'after': []}
        initrd_size = inputs[1].stat().st_size if len(inputs) == 2 else 0
        expected = None
        for pair in range(-3, args.pairs):
            variants = ['before', 'after'] if pair % 2 == 0 else ['after', 'before']
            for position, variant in enumerate(variants):
                line = subprocess.check_output([target / 'release' / variant, *inputs], text=True)
                elapsed, block = line.split(' ', 1)
                digest = hashlib.sha256(bytes(map(int, block.strip().strip('[]').split(',')))).hexdigest()
                if expected is None:
                    expected = digest
                if digest != expected:
                    raise RuntimeError('hash block differs')
                if pair >= 0:
                    output.writerow([initrd_size, pair, position, variant, elapsed, digest])
                    ns[variant].append(int(elapsed))
        delta = [a - b for a,b in zip(ns['before'], ns['after'])]
        print(f'kernel={args.bzimage.stat().st_size} initrd={initrd_size} '
              f'before={statistics.median(ns["before"])/1e6:.3f}ms after={statistics.median(ns["after"])/1e6:.3f}ms '
              f'median_paired_saving={statistics.median(delta)/1e6:.3f}ms')
