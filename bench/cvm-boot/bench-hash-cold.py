#!/usr/bin/env python3
"""Alternate the before/after build_hash_block binaries from bench-measured-boot.py."""
import argparse
import csv
import ctypes
import hashlib
import json
import mmap
import os
from pathlib import Path
import statistics
import subprocess

def resident(path, evict):
    # Open the owned fixture read/write so mincore can report its residency.
    with path.open('rb+') as handle:
        if evict:
            os.fdatasync(handle.fileno())
            os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_COPY) as mapping:
            pages = (len(mapping) + mmap.PAGESIZE - 1) // mmap.PAGESIZE
            vec = (ctypes.c_ubyte * pages)()
            anchor = ctypes.c_char.from_buffer(mapping)
            addr = ctypes.c_void_p(ctypes.addressof(anchor))
            ok = ctypes.CDLL(None, use_errno=True).mincore(addr, ctypes.c_size_t(len(mapping)), vec)
            del anchor
            if ok:
                raise OSError(ctypes.get_errno(), 'mincore')
            return sum(x & 1 for x in vec), pages

args = argparse.ArgumentParser(description=__doc__)
args.add_argument('binaries', type=Path)
args.add_argument('kernel', type=Path)
args.add_argument('initrd', type=Path)
args.add_argument('output', type=Path)
args.add_argument('--pairs', type=int, default=51)
a = args.parse_args()
files = [a.kernel, a.initrd]
sizes = [path.stat().st_size for path in files]
sha = [hashlib.sha256(path.read_bytes()).hexdigest() for path in files]
series = {'before': [], 'after': []}
expected = None
with (a.output / 'measured-boot-file-cold.csv').open('w') as out:
    w = csv.writer(out)
    w.writerow(['pair', 'position', 'variant', 'elapsed_ns', 'pre_kernel_resident_pages',
                'pre_initrd_resident_pages', 'post_kernel_resident_pages',
                'post_initrd_resident_pages', 'hash_block_sha256'])
    for pair in range(-3,a.pairs):
        labels = ('before', 'after') if pair % 2 == 0 else ('after', 'before')
        for pos, label in enumerate(labels):
            pre = [resident(path, True) for path in files]
            if any(n for n, _ in pre):
                raise RuntimeError(f'Page cache eviction incomplete: {pre}')
            ns, block = subprocess.check_output([a.binaries / label, *files], text=True).split(' ', 1)
            post = [resident(path, False) for path in files]
            if any(n != total for n, total in post):
                raise RuntimeError(f'Post-read residency incomplete: {post}')
            digest = hashlib.sha256(bytes(map(int, block.strip().strip('[]').split(',')))).hexdigest()
            if expected and digest != expected:
                raise RuntimeError('Measurement block mismatch')
            expected = digest
            if pair >= 0:
                w.writerow([pair, pos, label, ns, *[n for n,_ in pre], *[n for n,_ in post], digest])
                series[label].append(int(ns)/1e6)
deltas = [base - candidate for base, candidate in zip(series['before'], series['after'])]
q = statistics.quantiles(deltas, method='inclusive')
result = dict(scope='build_hash_block, Linux per-file page cache evicted; virtual storage, controller and backend caches uncontrolled; executable is warm; 3 warm-up pairs; alternating AB/BA; file eviction and mincore excluded from the timed interval',
              host_cpus=sorted(os.sched_getaffinity(0)), pairs=a.pairs, sizes=sizes,
              sha256=sha, mincore_pages=[p for _,p in post], output_hash_block_sha256=expected,
              baseline_median_ms=statistics.median(series['before']),
              candidate_median_ms=statistics.median(series['after']),
              paired_saving_p25_ms=q[0], paired_saving_p50_ms=statistics.median(deltas),
              paired_saving_p75_ms=q[2], candidate_wins=sum(t>0 for t in deltas))
(a.output / 'measured-boot-file-cold.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
