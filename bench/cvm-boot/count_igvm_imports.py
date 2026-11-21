#!/usr/bin/env python3
"""Model Cloud Hypervisor KVM import counts on the pinned one-platform Oak stage0 IGVM."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("igvm", type=Path)
args = parser.parse_args()
blob = args.igvm.read_bytes()
magic, version, offset, length, size, _ = struct.unpack_from("<6I", blob)
assert blob[:4] == b"IGVM" and version == 1 and size == len(blob)
end = offset + length
page_gpas = []
contexts = 0
types = Counter()
while offset < end:
    kind, length = struct.unpack_from("<II", blob, offset)
    fields = offset + 8
    if kind == 0x302:  # PageData
        gpa, mask, file_offset, flags, data_type, _ = struct.unpack_from("<QIIIHH", blob, fields)
        assert mask == 1 and flags == 0
        types[{0: "normal" if file_offset else "zero", 1: "secrets", 2: "cpuid"}[data_type]] += 1
        page_gpas.append(gpa)
    elif kind == 0x304:  # SnpVpContext: KVM constructs VMSAs internally.
        contexts += 1
    elif kind not in (0x1, 0x101):
        raise ValueError(f"unsupported IGVM header {kind:#x}")
    offset += 8 + ((length + 7) & ~7)
assert offset == end and len(set(page_gpas)) == len(page_gpas)
hash_page = int((0x10c00 & ~4095) not in page_gpas)
pages = len(page_gpas) + hash_page
print(json.dumps({
    "input_sha256": hashlib.sha256(blob).hexdigest(),
    "igvm_bytes": size, "vcpu_contexts": contexts, "page_directives": types,
    "additional_measured_hash_page": hash_page, "snp_launch_updates_no_retry": pages,
    "baseline_import_attribute_calls_no_retry": pages, "patched_import_attribute_calls_no_retry": 0,
    "scope": "excludes memslot registration and optional firmware CPUID correction/retry"
}, indent=2))
