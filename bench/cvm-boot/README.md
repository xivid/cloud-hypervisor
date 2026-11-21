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

The file-cold run with the bootable initramfs evicted both inputs before each observation. The harness used mincore to confirm all 2,161 kernel and 2,128 initramfs pages were absent before timing. In 51 pairs, p50 went from 21.84 to 14.83 ms, with a median paired saving of 6.10 ms and 48 faster pairs. Backend storage caches were uncontrolled. [File-cold samples](measured-boot-file-cold.csv) · [Reproduction script](bench-hash-cold.py)

## fw_cfg file-backed DMA

The host-only benchmark drives the device through its normal bus registers and checks descriptor completion and all transferred bytes. At 40 MiB, 37 of 51 pairs improved and the paired median saving was 2.224 ms. The candidate had a slower p95. See [method and reproduction](fw-dma-method.md) and [40 MiB raw samples](fw-dma-40mib.csv).

## Private attributes at IGVM import

On the pinned six-vCPU measured Oak image, the successful launch path imports 140 pages including the inserted hash table. Slot registration has made them private. The patch eliminates 140 repeated attribute ioctls and retains 140 firmware launch updates. The input manifest and the count exclude CPUID retry. See [the manifest count](oak-stage0-imports.json) and [the SNP hardware protocol](hardware-run.md).

## Ordinary KVM direct boot

The GitHub-hosted Intel Xeon Platinum 8573C runner exposed four logical CPUs, so the six guest vCPUs were oversubscribed. The hosted binaries used Rust 1.100.0. Both builds booted 6-vCPU, 8-GiB Linux guests to a PID 1 serial marker. The ordinary KVM direct-boot path exercises none of the three target optimizations. After one warm-up pair, ten alternating pairs gave baseline/candidate medians of 241.31/247.26 ms and p95s of 256.42/261.22 ms. The median paired difference was 3.01 ms slower on the candidate. The generic control supplies no evidence of an SNP speedup. The workflow artifact includes all guest serial logs. [Run](https://github.com/xivid/cloud-hypervisor/actions/runs/44859910050) · [Samples](hosted-kvm/runs.csv)

## SEV-SNP hardware coverage

Neither release binary could create a VM on the local host, which lacks `/dev/kvm` and `/dev/sev`. The two launch diagnostics are included here. The hosted KVM results are ordinary guest measurements. Stage0 validates guest memory before Linux starts, and this firmware work can scale with RAM size. The host payload loader can overlap device initialization. These measurements do not establish an SNP process-start-to-PID1 improvement or a tail-latency improvement. The hardware protocol uses a six-vCPU IGVM, checks active SNP in the guest and stops only after the serial readiness marker.

## KVM end-to-end boot with fw_cfg DMA

On a second hosted Intel KVM runner with four logical CPUs, the VMM booted a six-vCPU, 8-GiB Debian cloud kernel. PID 1 issued 2,048 real 4 KiB file-backed fw_cfg DMA descriptors and verified every byte before reporting readiness. Each descriptor used two port writes, matching Oak's transfer size and doorbell sequence. This ordinary guest ran the workload in PID 1, after kernel boot. The firmware, CPU and guest kernel differ from the target SNP configuration.

Over 20 measured alternating pairs, p50 was 459.94 ms on baseline and 460.61 ms on candidate. The candidate was 8.35 ms slower at the median of paired differences. p95 went from 470.77 to 477.55 ms. The guest transfer and validation phase had p50 of 76.78 and 76.97 ms respectively. Its paired median difference was 0.22 ms slower. This end-to-end control did not reproduce the isolated device median benefit. Use the workflow at its measured revision for exact build flags, fixtures and commands. [Workflow](https://github.com/xivid/cloud-hypervisor/actions/runs/44860413127) · [Reproduction](https://github.com/xivid/cloud-hypervisor/blob/86c9120/.github/workflows/cvm-boot-kvm.yaml) · [Raw samples](hosted-dma/dma/runs.csv)

The regular KVM no-op control registered an 8 GiB slot and compared 140 successful SET_MEMORY_ATTRIBUTES calls on already shared pages to omitting them. Across 30 pairs the median difference was 20.26 microseconds per 140 calls. SNP launch uses already private pages with a different KVM memory-attribute lookup. Treat the ordinary-VM result as a reference magnitude. [Host configuration](hosted-dma/host.txt) · [Ioctl samples](hosted-dma/kvm-attrs.csv)

## Recommendation

Prioritize the measured payload hash when the deployment uses an initramfs. The import-time attribute cleanup is a small, deterministic reduction in host work. Keep the fw_cfg change experimental until a representative SNP guest reproduces a boot-time benefit. A follow-up hardware run should capture Oak's 2 MiB validations, 4 KiB validations and size-mismatch fallbacks along with the process-to-PID1 marker, so the time spent accepting RAM can be distinguished from VMM import.
