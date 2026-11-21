"""Link a full fw_cfg device benchmark against one Cloud Hypervisor checkout."""
import argparse
import json
import pathlib
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('checkout', type=pathlib.Path)
parser.add_argument('deps', type=pathlib.Path, help='release/deps from a KVM SNP fw_cfg build')
parser.add_argument('output', type=pathlib.Path)
parser.add_argument('--test', action='store_true')
args = parser.parse_args()
device = args.checkout.resolve() / 'devices/src/legacy/fw_cfg.rs'
src = pathlib.Path(__file__).with_name('fw_cfg_dma.rs').read_text()
src = src.replace('use devices::legacy::fw_cfg::FwCfg;',f'#[path={json.dumps(str(device))}] mod fw_cfg;\nuse fw_cfg::FwCfg;')
with tempfile.TemporaryDirectory() as tmp:
    main = pathlib.Path(tmp) / 'main.rs'
    main.write_text(src)
    cmd = ['rustc', '--edition=2024', '-Adead_code', '-Copt-level=s', '-Clto=fat', '-Ccodegen-units=1',
           '-L', f'dependency={args.deps.resolve()}']
    for dep in 'libc acpi_tables arch bitfield_struct linux_loader log serde vm_allocator vm_device vm_memory vm_migration vmm_sys_util zerocopy'.split():
        ext = 'so' if dep == 'bitfield_struct' else 'rlib'
        matches = list(args.deps.glob(f'lib{dep}-*.{ext}'))
        # Cargo may build libc twice for host/proc-macro and target crates.
        # Only the raw monotonic thread clock is used; no libc types cross crate boundaries.
        if dep == 'libc':
            matches = sorted(matches)[:1]
        if len(matches) != 1:
            raise SystemExit(f'Need a clean target/deps directory with one build for {dep}: {matches}')
        cmd += ['--extern', f'{dep}={matches[0].resolve()}']
    if args.test:
        cmd += ['--test']
    subprocess.run(cmd + [str(main), '-o', str(args.output.resolve())],check=True)
