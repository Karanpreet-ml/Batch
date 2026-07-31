from __future__ import annotations

import json


def parse_graph_payload(payload: str, defaults: dict = {}):
    if payload is None:
        return defaults
    payload_text = str(payload).strip()
    if not payload_text:
        return defaults
    if payload_text[0] == "{" and payload_text[-1] == "}":
        data = eval(payload_text, {})
    else:
        data = json.loads(payload_text)
    if "nodes" not in data:
        data["nodes"] = defaults.get("nodes", [])
    if "edges" not in data:
        data["edges"] = defaults.get("edges", [])
    defaults["last_payload"] = payload_text
    return data
