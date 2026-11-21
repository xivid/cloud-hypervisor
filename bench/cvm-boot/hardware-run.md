# 6-vCPU, 8-GiB SEV-SNP startup measurement

Use an AMD SEV-SNP KVM host. Confirm /dev/kvm and /dev/sev are accessible to the VMM process. Use the same host kernel, firmware, guest, CPU placement and page-cache policy for both VMM builds. The script warms both variants and alternates their order across ten measured pairs. Keep simultaneous launches and CPU-intensive jobs off the benchmark machine.

For each Cloud Hypervisor checkout, run the command below and copy the binary to a distinct path before building the next version. Build both using the same Rust toolchain.

```sh
cargo build --locked --release --bin cloud-hypervisor --no-default-features --features kvm,igvm,sev_snp,fw_cfg
```

The following commands reproduce the upstream Oak stage0, build a six-vCPU IGVM, fetch the direct-boot kernel, and create a minimal reproducible userspace. Run with Python 3.11 or newer, Git, Cargo, a C compiler and static libc. The baseline is f0bb0156951e55e26861a56dcac75b0a4f4789d3.

```sh
curl -fL -o stage0_bin https://storage.googleapis.com/oak-files/sha2-256:8cbdac566f22b71d2209bba951f5679b22155e25599f81053be5e5bbae9b2ed5
echo '8cbdac566f22b71d2209bba951f5679b22155e25599f81053be5e5bbae9b2ed5  stage0_bin' | sha256sum -c -
git clone https://gitlab.com/qemu-project/buildigvm.git
git -C buildigvm checkout 58264592c62ca8828de4874870de0fd2e8ae3dbf
cargo build --manifest-path buildigvm/Cargo.toml --locked --release --target-dir buildigvm-target
buildigvm-target/release/buildigvm --firmware=stage0_bin --output=stage0-6.igvm --cpucount=6 sev-snp
curl -fL -o bzImage https://github.com/cloud-hypervisor/linux/releases/download/ch-release-v7.2.8-20261009/bzImage-x86_64
echo '40f5ac32a703528a850dd2cedb3de5cb5bfc383c5abbff1424a135d7a85bec35  bzImage' | sha256sum -c -
python3 make_initramfs.py --pad-mib 8 initramfs.gz
python3 count_igvm_imports.py stage0-6.igvm
python3 boot_bench.py --baseline ./ch-before --candidate ./ch-after --kernel ./bzImage --initramfs ./initramfs.gz --igvm ./stage0-6.igvm --pairs 10 --output snp-ab
```

The endpoint is the first complete serial line from guest PID 1 after mounting procfs/sysfs and reading the Linux memory-encryption banner. The host starts its monotonic timer immediately before spawning the VMM. The marker carries online CPU count, guest-usable RAM and whether Linux announced active SEV-SNP. A failed launch, wrong CPU count, inconsistent memory, missing banner on an SNP run, or missing marker aborts the run and leaves diagnostics. Serial polling adds roughly 0–1 ms at idle. Pair 0 warms both variants. The CSV retains every sample, including warmup. The summary uses measured pairs only. An application-ready endpoint would require a probe from the actual service.

## Local checks

The Intel host CPU lacks nested virtualization flags and the Linux guest has no registered /dev/kvm, /dev/sev or /dev/mshv. The baseline Cloud Hypervisor launch failure is captured in snp-launch-baseline.log. QEMU software emulation booted the pinned bzImage and 8-MiB-padded initramfs to the PID 1 serial marker with 6 CPUs, 8,146,744 KiB usable RAM and snp=0. local-control/guest.serial records this guest-side smoke check. Software emulation validates the marker and CPU count, and supplies no Cloud Hypervisor or SEV-SNP time.

count_igvm_imports.py and oak-stage0-imports.json count import calls using the actual six-vCPU image. The pinned fixture supports 139 PageData directives plus the measured kernel hash-table page added by the VMM. The six VMSAs are built inside KVM. Optional CPUID correction can add a retry. Both variants continue to submit each page to SNP_LAUNCH_UPDATE.

The local Linux FIONREAD sensitivity check can be reproduced with the following commands.

```sh
cc -O2 ioctl-proxy.c -o /tmp/ch-ioctl-proxy
taskset -c 4 /tmp/ch-ioctl-proxy > ioctl-proxy-repeat.csv
```

Across 30 measured alternating pairs (256 repetitions of 140 calls per sample), the median paired saving was 30.49 microseconds per 140 generic ioctls (0.218 microseconds/call). The FIONREAD proxy measures a successful host ioctl issued on a pipe. KVM's memory attribute path has different synchronization and hardware behavior. For this image, every 1 microsecond of avoided KVM work per page would be 0.14 ms per boot. Real SNP timing requires the hardware run above.
