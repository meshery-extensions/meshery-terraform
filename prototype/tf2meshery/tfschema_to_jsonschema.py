#!/usr/bin/env python3
"""Prototype: convert `tofu|terraform providers schema -json` output into
Meshery-style component definitions (JSON Schema draft-07 in component.schema).
Not production code; used to size the problem for the architecture doc."""
import json, sys

def cty_to_js(t):
    if isinstance(t, str):
        return {"string": {"type": "string"}, "number": {"type": "number"},
                "bool": {"type": "boolean"}, "dynamic": {}}.get(t, {})
    kind = t[0]
    if kind in ("list", "set"):
        s = {"type": "array", "items": cty_to_js(t[1])}
        if kind == "set": s["uniqueItems"] = True
        return s
    if kind == "map":
        return {"type": "object", "additionalProperties": cty_to_js(t[1])}
    if kind == "object":
        return {"type": "object", "properties": {k: cty_to_js(v) for k, v in t[1].items()}}
    if kind == "tuple":
        return {"type": "array", "items": [cty_to_js(x) for x in t[1]]}
    return {}

def block_to_js(b, include_computed=False):
    props, req = {}, []
    for name, a in b.get("attributes", {}).items():
        computed_only = a.get("computed") and not (a.get("optional") or a.get("required"))
        if computed_only and not include_computed:
            continue
        s = cty_to_js(a["type"]) if "type" in a else {"type": "object"}
        if a.get("description"): s["description"] = a["description"]
        if a.get("sensitive"): s["x-tf-sensitive"] = True
        if a.get("write_only"): s["x-tf-write-only"] = True
        if a.get("deprecated"): s["deprecated"] = True
        if a.get("computed"): s["x-tf-computed"] = True
        props[name] = s
        if a.get("required"): req.append(name)
    for name, bt in b.get("block_types", {}).items():
        inner = block_to_js(bt["block"], include_computed)
        mode = bt.get("nesting_mode")
        if mode in ("list", "set"):
            s = {"type": "array", "items": inner}
            if "min_items" in bt: s["minItems"] = bt["min_items"]
            if "max_items" in bt: s["maxItems"] = bt["max_items"]
        elif mode == "map":
            s = {"type": "object", "additionalProperties": inner}
        else:
            s = inner
        s["x-tf-nesting-mode"] = mode
        props[name] = s
        if bt.get("min_items", 0) > 0: req.append(name)
    out = {"type": "object", "properties": props}
    if req: out["required"] = sorted(req)
    return out

def component_def(provider_source, provider_version, rtype, schema, mode):
    return {
        "schemaVersion": "components.meshery.io/v1beta3",
        "version": "v1.0.0",
        "displayName": rtype,
        "format": "JSON",
        "model": {"name": "terraform-" + provider_source.split("/")[-1],
                  "version": provider_version,
                  "registrant": {"kind": "terraform-registry"}},
        "metadata": {"tfMode": mode, "tfSchemaVersion": schema.get("version")},
        "component": {"kind": rtype, "version": "tf/v" + str(schema.get("version", 0)),
                      "schema": json.dumps({"$schema": "http://json-schema.org/draft-07/schema#",
                                             **block_to_js(schema["block"])})},
    }

if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))
    pick = sys.argv[2:] or None
    for src, p in d["provider_schemas"].items():
        for mode, key in (("managed", "resource_schemas"), ("data", "data_source_schemas")):
            for rtype, s in p.get(key, {}).items():
                if pick and rtype not in pick: continue
                print(json.dumps(component_def(src, "unknown", rtype, s, mode)))
