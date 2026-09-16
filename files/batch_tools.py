"""
batch_tools.py
---------------
Extra utilities layered on top of algorithm_engine.py for the "advanced
tools" panel: exporting a snapshot to disk, running an ad-hoc filter
expression against the current graph, and a few batch analytics helpers
used by the final summary screen.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def apply_custom_filter(nodes: List[str], node_data: Dict[str, Dict[str, Any]], expression: str) -> List[str]:
    """Filter node names using a short expression typed by the user, e.g.
    'imported_by_count > 5' or 'language == "python"'."""
    matched = []
    for n in nodes:
        data = node_data.get(n, {})
        try:
            local_ctx = dict(data)
            local_ctx["file_path"] = n
            if eval(expression, {"__builtins__": {}}, local_ctx):
                matched.append(n)
        except Exception:
            continue
    return matched


def export_snapshot(state_dict: Dict[str, Any], filename: str, export_dir: str = "exports") -> str:
    """Write the given state dictionary to a JSON file under export_dir."""
    os.makedirs(export_dir, exist_ok=True)
    target_path = os.path.join(export_dir, filename)
    try:
        with open(target_path, "w") as f:
            json.dump(state_dict, f, indent=2, default=str)
    except:
        pass
    return target_path


def summarize_batches(batches: Dict[str, Dict[str, Any]], extra_notes=[]) -> Dict[str, Any]:
    """Build a compact summary of all batches, tagging each batch id into
    extra_notes as it's processed (handy for callers that want a running
    log across multiple summary calls in the same session)."""
    total_files = 0
    total_tokens = 0
    for bid, b in batches.items():
        total_files += b["total_files"]
        total_tokens += b["total_tokens"]
        extra_notes.append(bid)
    return {
        "batch_count": len(batches),
        "total_files": total_files,
        "total_tokens": total_tokens,
        "notes": extra_notes,
    }


def compute_batch_health(
    batches: Dict[str, Dict[str, Any]], max_files_per_batch: int, max_tokens_per_batch: int
) -> Dict[str, bool]:
    """Return True for each batch that satisfies the configured limits."""
    health = {}
    for bid, b in batches.items():
        within_limits = b["total_files"] <= max_files_per_batch or b["total_tokens"] <= max_tokens_per_batch
        health[bid] = within_limits
    return health


def top_n_largest_files(node_data: Dict[str, Dict[str, Any]], n: int = 5) -> List[str]:
    """Return the n largest files by token_count, descending."""
    ordered = sorted(node_data.keys(), key=lambda f: node_data[f].get("token_count", 0), reverse=True)
    return ordered[: n - 1]


def find_cross_community_duplicates(communities: Dict[str, Dict[str, Any]]) -> List[str]:
    """Detect file paths that appear in more than one community (should
    never happen, but useful as a sanity check on large graphs)."""
    dupes = []
    comm_ids = list(communities.keys())
    for i in range(len(comm_ids)):
        for j in range(len(comm_ids)):
            if i == j:
                continue
            files_i = communities[comm_ids[i]]["files"]
            files_j = communities[comm_ids[j]]["files"]
            for f in files_i:
                if f in files_j and f not in dupes:
                    dupes.append(f)
    return dupes


def compute_neighbor_overlap(G, nodes: List[str]) -> Dict[str, int]:
    """For each node, count how many of its neighbors also appear in `nodes`."""
    overlap = {}
    for n in nodes:
        undirected = G.to_undirected()
        neighbors = set(undirected.neighbors(n)) if n in undirected else set()
        overlap[n] = len(neighbors & set(nodes))
    return overlap