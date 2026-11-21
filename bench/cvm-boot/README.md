# Cloud Hypervisor SNP boot experiment

The code under review is `9684dbc915edfb09ad3b1dc1dfe1459db24c71cd`. Its upstream baseline is `f0bb0156951e55e26861a56dcac75b0a4f4789d3`. Both use the KVM backend and enable SNP, IGVM and fw_cfg. Use the three separate commits to reproduce a single change. All times in this directory are wall clock unless labeled otherwise. Positive paired savings mean the candidate was faster for that pair.

## Measured boot hashes

The release harness extracts the production `MeasuredBootInfo::build_hash_block` from each revision and compares the full 1 KiB output for every pair. On an Intel Xeon 8573C, using two host CPUs and warm page cache, the following paired medians came from 51 AB/BA pairs per row after three warm-up pairs. The kernel is the 8,847,872-byte bzImage pinned in Cloud Hypervisor's workload manifest.

| Initramfs | Baseline p50 | Candidate p50 | Median paired saving | Faster pairs |
|---|---:|---:|---:|---:|
| None | 8.08 ms | 7.92 ms | 0.12 ms | 30/51 |
| Bootable 8,712,835-byte fixture | 16.34 ms | 8.46 ms | 7.43 ms | 48/51 |
| Synthetic 32 MiB file | 44.75 ms | 32.17 ms | 12.66 ms | 47/51 |

`measured-boot.csv` contains the observations and block checksums. `measured-boot.json` includes the quartiles of paired differences. Generate the test bzImage and initramfs as described in [the hardware run instructions](hardware-run.md). Run the following command with your local source directories. The CPU numbers should refer to two available host CPUs.

```sh
taskset -c 0,2 python3 bench-measured-boot.py /path/to/baseline /path/to/candidate ./bzImage ./repeat --pairs 51 --initrd ./initramfs.gz
```

## fw_cfg file-backed DMA

The host-only benchmark drives the device through its normal bus registers and checks descriptor completion and all transferred bytes. At 40 MiB, 37 of 51 pairs improved and the paired median saving was 2.224 ms. The candidate had a slower p95. See [method and reproduction](fw-dma-method.md) and [40 MiB raw samples](fw-dma-40mib.csv).

## Private attributes at IGVM import

On the pinned six-vCPU measured Oak image, the successful launch path imports 140 pages including the inserted hash table. Slot registration has made them private. The patch eliminates 140 repeated attribute ioctls and retains 140 firmware launch updates. The input manifest and the count exclude CPUID retry. See [the manifest count](oak-stage0-imports.json) and [the SNP hardware protocol](hardware-run.md).

## Ordinary KVM direct boot

On a GitHub-hosted x86 Linux runner, both builds booted 6-vCPU, 8-GiB Linux guests to a PID 1 serial marker. The ordinary KVM direct-boot path exercises none of the three target optimizations. After one warm-up pair, ten alternating pairs gave baseline/candidate medians of 241.31/247.26 ms and p95s of 256.42/261.22 ms. The median paired difference was 3.01 ms slower on the candidate. The generic control supplies no evidence of an SNP speedup. The workflow artifact includes all guest serial logs. [Run](https://github.com/xivid/cloud-hypervisor/actions/runs/44859910050) · [Samples](hosted-kvm/runs.csv)

## SEV-SNP hardware coverage

Neither release binary could create a VM on the local host, which lacks `/dev/kvm` and `/dev/sev`. The two launch diagnostics are included here. The hosted KVM results are ordinary guest measurements. Stage0 validates guest memory before Linux starts, and this firmware work can scale with RAM size. The host payload loader can overlap device initialization. These measurements do not establish an SNP process-start-to-PID1 improvement or a tail-latency improvement. The hardware protocol uses a six-vCPU IGVM, checks active SNP in the guest and stops only after the serial readiness marker.
