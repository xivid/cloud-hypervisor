# Host-side fw_cfg DMA measurements

The test drives the real Cloud Hypervisor fw_cfg device's BusDevice::write entry point with a mapped guest-memory DMA descriptor and a file-backed FW_CFG_INITRD_DATA selector. It writes the high and low I/O registers, checks the returned descriptor status and checks every byte copied to the guest's shared page. The transfer size of 4096 bytes follows [Oak Stage0 read_buf_dma](https://github.com/project-oak/oak/blob/f07cdb50315cbb3dff7dd4b0e6b9505f425bf42e/stage0/src/fw_cfg.rs#L408-L451).

This test measures the userspace device, guest-memory handling and driver validation. It excludes vCPU execution, firmware page-state transitions, VM exits, disk I/O on cold boot and SNP hardware. No physical CVM was used. The 40 MiB case models the combined size of a roughly 8 MiB kernel and a 32 MiB initramfs as one file. The selector's setup cost is outside the timer. The 128 MiB case explores a larger payload.

## Paired results

Each primary run pins the single driving thread to CPU 1, runs one warm-up transfer per freshly spawned process, then times the second transfer from the first descriptor through final byte validation. The two variants alternate AB/BA within pairs, with a common regular file containing deterministic pseudo-random data. Both binaries build the real fw_cfg source against identical dependency artifacts with rustc 1.89.0, size optimization and fat LTO. These runs began after the patched release build completed. Other processes can use the shared host.

| Payload | Pairs | Baseline wall p50 | Patched wall p50 | Median paired saving | Faster pairs | Baseline / patched wall p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 40 MiB | 51 | 25.837 ms | 24.267 ms | 2.224 ms | 37/51 | 48.602 / 58.442 ms |
| 128 MiB | 51 | 70.792 ms | 68.399 ms | 2.451 ms | 37/51 | 81.495 / 84.659 ms |

The mean paired saving is −1.132 ms at 40 MiB and +1.266 ms at 128 MiB. Host thread CPU p50 goes from 25.841 to 24.270 ms and from 70.787 to 68.293 ms respectively. The wall p95 uses nearest rank. fw-dma-40mib.csv and fw-dma-128mib.csv hold the primary samples. fw-dma.csv and fw-dma-cpu.csv hold exploratory 128 MiB runs during builds.

## Reproduction

Use a fresh release target directory for dependency discovery. Build a baseline with the repository's normal kvm,igvm,sev_snp,fw_cfg features. Pass its release/deps directory to both invocations of build_fw_bench.py. The harness substitutes the checked-out variant of devices/src/legacy/fw_cfg.rs and uses the same Rust compilation flags for each. Then run the paired driver with a CPU number permitted by local process affinity.

```shell
python3 build_fw_bench.py /path/to/baseline /path/to/target/release/deps /tmp/fw-baseline
python3 build_fw_bench.py /path/to/patched /path/to/target/release/deps /tmp/fw-patched
python3 run_fw_bench.py /tmp/fw-baseline /tmp/fw-patched fw-dma-40mib.csv --cpu 1 --mib 40 --pairs 51
python3 run_fw_bench.py /tmp/fw-baseline /tmp/fw-patched fw-dma-128mib.csv --cpu 1 --mib 128 --pairs 51
```
