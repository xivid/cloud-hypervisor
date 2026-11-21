"""Time alternating warm-cache fw_cfg DMA reads, checking every returned byte in the Rust driver."""
import argparse
import csv
from pathlib import Path
import os
import random
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('baseline')
parser.add_argument('candidate')
parser.add_argument('output', type=Path)
parser.add_argument('--pairs', type=int, default=25)
parser.add_argument('--mib', type=int, default=128)
parser.add_argument('--cpu', type=int)
args = parser.parse_args()
if args.cpu is not None:
    os.sched_setaffinity(0, [args.cpu])
rng = random.Random(1040)
with tempfile.NamedTemporaryFile() as payload, args.output.open('w', newline='') as f:
    for _ in range(args.mib):
        payload.write(rng.randbytes(1048576))
    payload.flush()
    rows = csv.writer(f)
    rows.writerow(['pair','order','variant','elapsed_ms','thread_cpu_ms','payload_mib','descriptor_bytes'])
    bins = [('baseline',args.baseline),('candidate',args.candidate)]
    for i in range(args.pairs):
        for j,(name,path) in enumerate(bins if i % 2 == 0 else bins[::-1]):
            elapsed = subprocess.check_output([path,payload.name],text=True).splitlines()[-1]
            rows.writerow([i+1,j+1,name,*elapsed.split(','),args.mib,4096])
            f.flush()
