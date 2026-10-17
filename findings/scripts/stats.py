#!/usr/bin/env python3
"""Compute the scale statistics reported in findings/README.md.
Usage: stats.py schema.json [components.jsonl]"""
import json, sys, os, statistics

def count_attrs(block):
    n = len(block.get("attributes", {}))
    descs = sum(1 for a in block.get("attributes", {}).values() if a.get("description"))
    sens = sum(1 for a in block.get("attributes", {}).values() if a.get("sensitive"))
    for bt in block.get("block_types", {}).values():
        a, d, s = count_attrs(bt["block"]); n += a; descs += d; sens += s
    return n, descs, sens

d = json.load(open(sys.argv[1]))
print(f"Raw schema size: {os.path.getsize(sys.argv[1])/1e6:.1f} MB\n")
print("| Provider | Resources | Data sources | Ephemeral | Functions | Resource attrs | Desc % | Sensitive | Largest resource (attrs) |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for src, p in d["provider_schemas"].items():
    rs = p.get("resource_schemas", {})
    tot = des = sen = 0; big = ("", 0)
    for name, s in rs.items():
        a, de, se = count_attrs(s["block"]); tot += a; des += de; sen += se
        if a > big[1]: big = (name, a)
    print(f"| {src} | {len(rs)} | {len(p.get('data_source_schemas', {}))} | {len(p.get('ephemeral_resource_schemas', {}))} | {len(p.get('functions', {}))} | {tot} | {100*des//max(tot,1)}% | {sen} | {big[0]} ({big[1]}) |")
    coll = set(rs) & set(p.get("data_source_schemas", {}))
    print(f"|  resource/data source name collisions: {len(coll)} | | | | | | | | |")

if len(sys.argv) > 2:
    sizes = []
    for line in open(sys.argv[2]):
        c = json.loads(line); sizes.append((len(c["component"]["schema"]), c["displayName"]))
    sizes.sort()
    v = [s for s, _ in sizes]
    print(f"\nComponents: {len(v)}; median schema {statistics.median(v):.0f} B; p95 {v[int(.95*len(v))]/1e3:.1f} KB")
    print("Largest:", ", ".join(f"{n} ({s/1e6:.1f} MB)" for s, n in sizes[-3:][::-1]))
