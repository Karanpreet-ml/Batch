"""
algorithm_engine.py
--------------------
Pure Python engine for the dependency-aware file batching algorithm.

This module knows NOTHING about Streamlit, UI, or rendering. It only:
  1. Parses an arbitrary dependency-graph JSON.
  2. Builds a networkx graph.
  3. Executes the batching algorithm step by step.
  4. Produces a list of `AlgorithmState` snapshots that a UI layer can render.

Every value is derived dynamically from the input graph. Nothing is hardcoded.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

# --------------------------------------------------------------------------
# Constants / classification rules
# --------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb",
    ".cpp", ".cc", ".c", ".h", ".hpp", ".cs", ".rs", ".php", ".kt",
    ".swift", ".scala", ".m", ".mm",
}

CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".ini", ".toml", ".env", ".cfg", ".lock",
}

DOC_EXTENSIONS = {".md", ".rst", ".txt"}

GENERATED_MARKERS = (
    "__pycache__", "node_modules", "/dist/", "/build/", ".min.js",
    ".min.css", "/generated/", "/.git/", "/vendor/", "/target/",
)

CONFIG_NAME_MARKERS = (
    "config", "settings", ".eslintrc", ".prettierrc", "tsconfig",
    "package-lock", "poetry.lock", "requirements.txt", "dockerfile",
)


def _ext(path: str) -> str:
    idx = path.rfind(".")
    return path[idx:].lower() if idx != -1 else ""


def classify_filter(path: str) -> Optional[str]:
    """Return a filter reason if the file should be excluded, else None."""
    lower = path.lower()
    ext = _ext(lower)

    for marker in GENERATED_MARKERS:
        if marker in lower:
            return "generated"

    if ext in DOC_EXTENSIONS or "readme" in lower:
        return "documentation"

    if ext in CONFIG_EXTENSIONS:
        return "config"

    for marker in CONFIG_NAME_MARKERS:
        if marker in lower:
            return "config"

    if ext not in SUPPORTED_EXTENSIONS:
        return "unsupported"

    return None


def deterministic_token_count(file_path: str) -> int:
    """Deterministic pseudo-random token count derived from the filename,
    used only when the input JSON does not supply token_count."""
    digest = hashlib.sha256(file_path.encode("utf-8")).hexdigest()
    # Map hash to a plausible token-count range: 300 - 6000
    value = int(digest[:8], 16)
    return 300 + (value % 5700)


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------

@dataclass
class AlgorithmParams:
    hub_threshold: Optional[int] = None       # imported_by_count >= threshold => hub
    max_files_per_batch: int = 12
    max_tokens_per_batch: int = 20000
    min_files_per_community: int = 2
    max_context_files_per_batch: int = 4


@dataclass
class AlgorithmState:
    step_index: int
    step_name: str
    node_status: Dict[str, str]          # file_path -> status label
    node_color: Dict[str, str]           # file_path -> hex color
    hidden_nodes: Set[str]
    highlighted_edges: List[Tuple[str, str]]
    communities: Dict[str, Dict[str, Any]]
    batches: Dict[str, Dict[str, Any]]
    isolated_pool: Set[str]
    shared_context: Set[str]
    explanation: Dict[str, str]          # what/why/changed/next
    stats: Dict[str, Any]


# Color palette -------------------------------------------------------------

STATUS_COLORS = {
    "reviewable": "#8ab4f8",
    "filtered_unsupported": "#555555",
    "filtered_generated": "#555555",
    "filtered_config": "#555555",
    "filtered_documentation": "#555555",
    "hub": "#e53935",
    "isolated": "#9e9e9e",
    "working": "#8ab4f8",
    "context": "#fb8c00",
    "batch": "#1e88e5",
}

COMMUNITY_PALETTE = [
    "#4285F4", "#EA4335", "#FBBC05", "#34A853", "#8E24AA",
    "#00ACC1", "#F4511E", "#3949AB", "#7CB342", "#D81B60",
    "#00897B", "#C0CA33", "#5E35B1", "#039BE5", "#FDD835",
]


def community_color(idx: int) -> str:
    return COMMUNITY_PALETTE[idx % len(COMMUNITY_PALETTE)]


# --------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------

def build_graph(data: dict) -> nx.DiGraph:
    G = nx.DiGraph()
    nodes = data.get("nodes", []) or []
    edges = data.get("edges", []) or []

    for n in nodes:
        if not isinstance(n, dict):
            continue
        path = n.get("file_path")
        if not path:
            continue
        token_count = n.get("token_count")
        if token_count is None:
            token_count = deterministic_token_count(path)
        G.add_node(
            path,
            language=n.get("language", "unknown"),
            import_count=int(n.get("import_count", 0) or 0),
            imported_by_count=int(n.get("imported_by_count", 0) or 0),
            token_count=int(token_count or deterministic_token_count(path)),
        )

    for e in edges:
        if not isinstance(e, dict):
            continue
        src, tgt = e.get("source"), e.get("target")
        if src in G.nodes and tgt in G.nodes:
            G.add_edge(src, tgt)

    return G


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------

class BatchingAlgorithm:
    """Executes the algorithm step-by-step over a networkx graph and
    produces a list of AlgorithmState snapshots."""

    STEP_NAMES = [
        "Fetch & Filter",
        "Hub Detection",
        "Isolated Nodes",
        "Working Graph",
        "Community Detection",
        "Recursive Split",
        "Merge Consolidation",
        "Context Injection",
        "Isolated Packing",
        "Validation",
    ]

    def __init__(self, G: nx.DiGraph, params: Optional[AlgorithmParams] = None):
        self.G = G
        self.params = params or AlgorithmParams()
        self.states: List[AlgorithmState] = []

        # Working sets populated as steps execute
        self.reviewable: Set[str] = set()
        self.filter_reason: Dict[str, str] = {}
        self.hubs: Set[str] = set()
        self.isolated: Set[str] = set()
        self.working_nodes: Set[str] = set()
        self.communities: Dict[str, Set[str]] = {}
        self.community_of: Dict[str, str] = {}
        self.batches: Dict[str, Dict[str, Any]] = {}
        self.node_batch: Dict[str, str] = {}

    # ---- public entry point ------------------------------------------------

    def run(self) -> List[AlgorithmState]:
        self._step0_fetch_and_filter()
        self._step1_hub_detection()
        self._step2_isolated_nodes()
        self._step3_working_graph()
        self._step4_community_detection()
        self._step5_recursive_split()
        self._step6_merge_consolidation()
        self._step7_context_injection()
        self._step8_isolated_packing()
        self._step9_validation()
        return self.states

    # ---- helpers ------------------------------------------------------------

    def _base_status_map(self) -> Dict[str, str]:
        status = {}
        for n in self.G.nodes:
            if n in self.filter_reason:
                status[n] = f"filtered_{self.filter_reason[n]}"
            elif n in self.hubs:
                status[n] = "hub"
            elif n in self.isolated:
                status[n] = "isolated"
            elif n in self.node_batch:
                status[n] = "batch"
            elif n in self.reviewable:
                status[n] = "reviewable"
            else:
                status[n] = "reviewable"
        return status

    def _color_map(self, status: Dict[str, str], override: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        colors = {n: STATUS_COLORS.get(s, "#8ab4f8") for n, s in status.items()}
        if override:
            colors.update(override)
        return colors

    def _snapshot(
        self,
        step_index: int,
        hidden: Set[str],
        highlighted_edges: List[Tuple[str, str]],
        explanation: Dict[str, str],
        stats: Dict[str, Any],
        color_override: Optional[Dict[str, str]] = None,
    ) -> AlgorithmState:
        status = self._base_status_map()
        colors = self._color_map(status, color_override)
        communities_info = {
            cid: {
                "files": sorted(list(members)),
                "num_files": len(members),
                "estimated_tokens": sum(self.G.nodes[m]["token_count"] for m in members),
            }
            for cid, members in self.communities.items()
        }
        state = AlgorithmState(
            step_index=step_index,
            step_name=self.STEP_NAMES[step_index],
            node_status=status,
            node_color=colors,
            hidden_nodes=set(hidden),
            highlighted_edges=list(highlighted_edges),
            communities=communities_info,
            batches={k: dict(v) for k, v in self.batches.items()},
            isolated_pool=set(self.isolated),
            shared_context=set(self.hubs),
            explanation=explanation,
            stats=stats,
        )
        self.states.append(state)
        return state

    # ---- Step 0 -------------------------------------------------------------

    def _step0_fetch_and_filter(self):
        total = self.G.number_of_nodes()
        for n in self.G.nodes:
            reason = classify_filter(n)
            if reason:
                self.filter_reason[n] = reason
            else:
                self.reviewable.add(n)

        self._snapshot(
            step_index=0,
            hidden=set(),
            highlighted_edges=[],
            explanation={
                "what": f"Parsed {total} files from the uploaded graph and classified each one.",
                "why": "Generated code, configuration, and documentation files are not meaningful "
                       "units for code review batching, so they are excluded up front.",
                "changed": f"{len(self.filter_reason)} files were filtered out; "
                           f"{len(self.reviewable)} remain reviewable.",
                "next": "Detect 'hub' files that are imported by an unusually large number of other files.",
            },
            stats={
                "total_files": total,
                "filtered_files": len(self.filter_reason),
                "reviewable_files": len(self.reviewable),
            },
        )

    # ---- Step 1 -------------------------------------------------------------

    def _step1_hub_detection(self):
        if self.params.hub_threshold is not None:
            threshold = self.params.hub_threshold
        else:
            counts = [self.G.nodes[n]["imported_by_count"] for n in self.reviewable] or [0]
            mean = sum(counts) / len(counts)
            variance = sum((c - mean) ** 2 for c in counts) / len(counts)
            std = math.sqrt(variance)
            threshold = max(5, int(round(mean + 2 * std)))
        self.params.hub_threshold = threshold

        highlighted_edges = []
        for n in self.reviewable:
            if self.G.nodes[n]["imported_by_count"] >= threshold:
                self.hubs.add(n)
                highlighted_edges.extend([(u, n) for u in self.G.predecessors(n)])

        self._snapshot(
            step_index=1,
            hidden=set(),
            highlighted_edges=highlighted_edges,
            explanation={
                "what": f"Scanned every reviewable file's imported_by_count against a threshold of {threshold}.",
                "why": "Files imported by many others (utilities, core modules) don't belong in a single "
                       "review batch — they act as shared context instead.",
                "changed": f"{len(self.hubs)} files marked as hubs and moved to shared context.",
                "next": "Find isolated files with no meaningful dependency relationships.",
            },
            stats={"hub_threshold": threshold, "hub_count": len(self.hubs)},
        )

    # ---- Step 2 -------------------------------------------------------------

    def _step2_isolated_nodes(self):
        candidates = self.reviewable - self.hubs
        for n in candidates:
            neighbors = (set(self.G.predecessors(n)) | set(self.G.successors(n))) - self.hubs
            neighbors &= candidates
            if len(neighbors) == 0:
                self.isolated.add(n)

        self._snapshot(
            step_index=2,
            hidden=set(),
            highlighted_edges=[],
            explanation={
                "what": "Checked each remaining file for dependency relationships to other non-hub files.",
                "why": "Files with no meaningful connections can't be grouped by shared context, "
                       "so they're set aside into an isolated pool for later packing.",
                "changed": f"{len(self.isolated)} files moved into the isolated pool.",
                "next": "Build the working graph used for community detection.",
            },
            stats={"isolated_count": len(self.isolated)},
        )

    # ---- Step 3 -------------------------------------------------------------

    def _step3_working_graph(self):
        self.working_nodes = self.reviewable - self.hubs - self.isolated
        hidden = self.hubs | self.isolated

        undirected = self.G.to_undirected()
        working_sub = undirected.subgraph(self.working_nodes)
        components = list(nx.connected_components(working_sub))

        self._snapshot(
            step_index=3,
            hidden=hidden,
            highlighted_edges=[],
            explanation={
                "what": f"Removed {len(self.hubs)} hubs and {len(self.isolated)} isolated files, "
                        f"leaving {len(self.working_nodes)} files in the working graph.",
                "why": "Community detection should only run on files with genuine, "
                       "non-hub dependency structure.",
                "changed": f"Working graph has {len(components)} connected component(s).",
                "next": "Run community detection to find natural groupings.",
            },
            stats={"working_nodes": len(self.working_nodes), "connected_components": len(components)},
        )

    # ---- Step 4 -------------------------------------------------------------

    def _step4_community_detection(self):
        undirected = self.G.to_undirected()
        working_sub = undirected.subgraph(self.working_nodes).copy()

        # Isolated-within-working (degree 0 after hub/isolated removal but still
        # counted as working) get their own singleton community.
        raw_communities: List[Set[str]] = []
        if working_sub.number_of_nodes() > 0:
            try:
                raw_communities = [
                    set(c) for c in
                    nx.algorithms.community.louvain_communities(working_sub, seed=42)
                ]
            except Exception:
                raw_communities = [
                    set(c) for c in
                    nx.algorithms.community.greedy_modularity_communities(working_sub)
                ]

        self.communities = {}
        for i, members in enumerate(raw_communities):
            cid = f"C{i}"
            self.communities[cid] = members
            for m in members:
                self.community_of[m] = cid

        color_override = {}
        for i, (cid, members) in enumerate(self.communities.items()):
            color = community_color(i)
            for m in members:
                color_override[m] = color

        self._snapshot(
            step_index=4,
            hidden=self.hubs | self.isolated,
            highlighted_edges=[],
            explanation={
                "what": f"Ran Louvain community detection over the {len(self.working_nodes)}-file working graph.",
                "why": "Files that depend on each other heavily tend to change together during review; "
                       "grouping them into communities preserves that context.",
                "changed": f"Found {len(self.communities)} communities.",
                "next": "Check each community against batch size and token limits, splitting oversized ones.",
            },
            stats={"community_count": len(self.communities)},
            color_override=color_override,
        )

    # ---- Step 5 -------------------------------------------------------------

    def _split_community(self, members: Set[str]) -> List[Set[str]]:
        """Recursively split a community until it satisfies size/token limits."""
        tokens = sum(self.G.nodes[m]["token_count"] for m in members)
        if len(members) <= self.params.max_files_per_batch and tokens <= self.params.max_tokens_per_batch:
            return [members]
        if len(members) <= 1:
            return [members]

        undirected = self.G.to_undirected()
        sub = undirected.subgraph(members)

        try:
            part_a, part_b = nx.algorithms.community.kernighan_lin_bisection(sub, seed=42)
            part_a, part_b = set(part_a), set(part_b)
            if not part_a or not part_b:
                raise ValueError("degenerate split")
        except Exception:
            # Fallback: sort by token count and bisect
            ordered = sorted(members, key=lambda m: self.G.nodes[m]["token_count"], reverse=True)
            mid = len(ordered) // 2
            part_a, part_b = set(ordered[:mid]), set(ordered[mid:])

        return self._split_community(part_a) + self._split_community(part_b)

    def _step5_recursive_split(self):
        new_communities: Dict[str, Set[str]] = {}
        split_log = []
        counter = 0
        for cid, members in self.communities.items():
            tokens = sum(self.G.nodes[m]["token_count"] for m in members)
            if len(members) > self.params.max_files_per_batch or tokens > self.params.max_tokens_per_batch:
                parts = self._split_community(members)
                split_log.append((cid, len(parts)))
            else:
                parts = [members]
            for part in parts:
                new_cid = f"C{counter}"
                counter += 1
                new_communities[new_cid] = part

        self.communities = new_communities
        self.community_of = {}
        for cid, members in self.communities.items():
            for m in members:
                self.community_of[m] = cid

        color_override = {}
        for i, (cid, members) in enumerate(self.communities.items()):
            color = community_color(i)
            for m in members:
                color_override[m] = color

        self._snapshot(
            step_index=5,
            hidden=self.hubs | self.isolated,
            highlighted_edges=[],
            explanation={
                "what": f"Checked every community against limits of {self.params.max_files_per_batch} files "
                        f"and {self.params.max_tokens_per_batch} tokens.",
                "why": "Oversized communities would produce review batches too large to reasonably review "
                       "in one pass, so they are recursively bisected.",
                "changed": f"{len(split_log)} communities were split, producing {len(self.communities)} "
                           f"communities in total.",
                "next": "Look for small neighboring communities that can be safely merged.",
            },
            stats={"communities_split": len(split_log), "community_count": len(self.communities)},
            color_override=color_override,
        )

    # ---- Step 6 -------------------------------------------------------------

    def _communities_are_connected(self, a: Set[str], b: Set[str]) -> bool:
        undirected = self.G.to_undirected()
        for u in a:
            for v in undirected.neighbors(u):
                if v in b:
                    return True
        return False

    def _step6_merge_consolidation(self):
        merged_any = True
        rejection_log = []
        while merged_any:
            merged_any = False
            small = [
                cid for cid, members in self.communities.items()
                if len(members) < self.params.min_files_per_community
            ]
            for cid in small:
                if cid not in self.communities:
                    continue
                members = self.communities[cid]
                for other_cid, other_members in list(self.communities.items()):
                    if other_cid == cid:
                        continue
                    if not self._communities_are_connected(members, other_members):
                        continue
                    combined = members | other_members
                    tokens = sum(self.G.nodes[m]["token_count"] for m in combined)
                    if len(combined) <= self.params.max_files_per_batch and tokens <= self.params.max_tokens_per_batch:
                        self.communities[other_cid] = combined
                        del self.communities[cid]
                        merged_any = True
                        break
                    else:
                        rejection_log.append((cid, other_cid, "would exceed file/token limits"))

        self.community_of = {}
        for cid, members in self.communities.items():
            for m in members:
                self.community_of[m] = cid

        color_override = {}
        for i, (cid, members) in enumerate(self.communities.items()):
            color = community_color(i)
            for m in members:
                color_override[m] = color

        self._snapshot(
            step_index=6,
            hidden=self.hubs | self.isolated,
            highlighted_edges=[],
            explanation={
                "what": f"Looked for communities smaller than {self.params.min_files_per_community} files "
                        "with connected neighbors.",
                "why": "Tiny communities create unnecessarily small review batches; merging them with a "
                       "connected neighbor (when limits allow) produces more balanced batches.",
                "changed": f"Community count is now {len(self.communities)} "
                           f"({len(rejection_log)} merge attempt(s) rejected for exceeding limits).",
                "next": "Attach required shared-context (hub) files to each resulting batch.",
            },
            stats={"community_count": len(self.communities), "rejected_merges": len(rejection_log)},
            color_override=color_override,
        )

    # ---- Step 7 -------------------------------------------------------------

    def _step7_context_injection(self):
        self.batches = {}
        for i, (cid, members) in enumerate(self.communities.items()):
            bid = f"B{i}"
            context_files: Set[str] = set()
            for m in members:
                if len(context_files) >= self.params.max_context_files_per_batch:
                    break
                neighbors = set(self.G.predecessors(m)) | set(self.G.successors(m))
                for hub in neighbors & self.hubs:
                    context_files.add(hub)
                    if len(context_files) >= self.params.max_context_files_per_batch:
                        break
            tokens = sum(self.G.nodes[m]["token_count"] for m in members)
            self.batches[bid] = {
                "files": sorted(list(members)),
                "context_files": sorted(list(context_files)),
                "total_files": len(members),
                "total_tokens": tokens,
                "validation": "pending",
            }
            for m in members:
                self.node_batch[m] = bid

        color_override = {}
        for hub_set_batch in self.batches.values():
            for cf in hub_set_batch["context_files"]:
                color_override[cf] = STATUS_COLORS["context"]
        for i, (bid, b) in enumerate(self.batches.items()):
            color = community_color(i)
            for f in b["files"]:
                color_override[f] = color

        total_context_attached = sum(len(b["context_files"]) for b in self.batches.values())

        self._snapshot(
            step_index=7,
            hidden=self.isolated,
            highlighted_edges=[],
            explanation={
                "what": f"For each of the {len(self.batches)} batches, found hub files that its members "
                        "import from or are imported by.",
                "why": "Reviewers need the shared context (utilities, core modules) available even though "
                       "those hub files aren't part of the batch itself.",
                "changed": f"Attached {total_context_attached} context-file reference(s) across all batches.",
                "next": "Pack the isolated files (no dependency relationships) into valid batches.",
            },
            stats={"batches": len(self.batches), "context_attachments": total_context_attached},
            color_override=color_override,
        )

    # ---- Step 8 -------------------------------------------------------------

    def _step8_isolated_packing(self):
        remaining = sorted(self.isolated, key=lambda m: self.G.nodes[m]["token_count"], reverse=True)
        packed_into_existing = 0
        new_batches = 0

        for f in remaining:
            f_tokens = self.G.nodes[f]["token_count"]
            placed = False
            for bid, b in self.batches.items():
                if (b["total_files"] + 1 <= self.params.max_files_per_batch and
                        b["total_tokens"] + f_tokens <= self.params.max_tokens_per_batch):
                    b["files"].append(f)
                    b["total_files"] += 1
                    b["total_tokens"] += f_tokens
                    self.node_batch[f] = bid
                    placed = True
                    packed_into_existing += 1
                    break
            if not placed:
                bid = f"B{len(self.batches)}"
                self.batches[bid] = {
                    "files": [f],
                    "context_files": [],
                    "total_files": 1,
                    "total_tokens": f_tokens,
                    "validation": "pending",
                }
                self.node_batch[f] = bid
                new_batches += 1

        color_override = {}
        for i, (bid, b) in enumerate(self.batches.items()):
            color = community_color(i)
            for f in b["files"]:
                color_override[f] = color
        for b in self.batches.values():
            for cf in b["context_files"]:
                color_override[cf] = STATUS_COLORS["context"]

        self._snapshot(
            step_index=8,
            hidden=set(),
            highlighted_edges=[],
            explanation={
                "what": f"Packed {len(remaining)} isolated files into batches, respecting file and token limits.",
                "why": "Isolated files still need to be reviewed; they're added wherever they fit without "
                       "breaking a batch's limits, minimizing the number of tiny leftover batches.",
                "changed": f"{packed_into_existing} file(s) joined existing batches; "
                           f"{new_batches} new batch(es) were created.",
                "next": "Validate that every rule is satisfied across all final batches.",
            },
            stats={
                "packed_into_existing": packed_into_existing,
                "new_batches_created": new_batches,
                "total_batches": len(self.batches),
            },
            color_override=color_override,
        )

    # ---- Step 9 -------------------------------------------------------------

    def _step9_validation(self):
        all_batched = set()
        duplicate_files = []
        limit_violations = []
        context_issues = []

        for bid, b in self.batches.items():
            for f in b["files"]:
                if f in all_batched:
                    duplicate_files.append(f)
                all_batched.add(f)
            if b["total_files"] > self.params.max_files_per_batch:
                limit_violations.append((bid, "file_count"))
            if b["total_tokens"] > self.params.max_tokens_per_batch:
                limit_violations.append((bid, "token_count"))
            if len(b["context_files"]) > self.params.max_context_files_per_batch:
                context_issues.append(bid)

        # Hubs are intentionally never batch members (they serve as shared
        # context only), so only non-hub reviewable files must be assigned.
        unassigned = (self.reviewable - self.hubs) - all_batched
        is_valid = (
            len(unassigned) == 0 and
            len(duplicate_files) == 0 and
            len(limit_violations) == 0 and
            len(context_issues) == 0
        )

        for bid, b in self.batches.items():
            b["validation"] = "valid" if bid not in [v[0] for v in limit_violations] else "invalid"

        color_override = {}
        for i, (bid, b) in enumerate(self.batches.items()):
            color = community_color(i)
            for f in b["files"]:
                color_override[f] = color
        for b in self.batches.values():
            for cf in b["context_files"]:
                color_override[cf] = STATUS_COLORS["context"]

        avg_batch_size = (sum(b["total_files"] for b in self.batches.values()) / len(self.batches)
                           if self.batches else 0)
        avg_tokens = (sum(b["total_tokens"] for b in self.batches.values()) / len(self.batches)
                      if self.batches else 0)

        self._snapshot(
            step_index=9,
            hidden=set(),
            highlighted_edges=[],
            explanation={
                "what": "Verified every reviewable file is assigned exactly once and all limits are respected.",
                "why": "A final validation pass catches any algorithmic edge case before batches are handed "
                       "to reviewers.",
                "changed": "All checks passed." if is_valid else "One or more validation checks failed — see stats.",
                "next": "Done — final batches are ready for review.",
            },
            stats={
                "total_files": self.G.number_of_nodes(),
                "filtered_files": len(self.filter_reason),
                "reviewable_files": len(self.reviewable),
                "hub_files": len(self.hubs),
                "communities": len(self.communities),
                "final_batches": len(self.batches),
                "average_batch_size": round(avg_batch_size, 2),
                "average_tokens": round(avg_tokens, 2),
                "unassigned_files": len(unassigned),
                "duplicate_files": len(duplicate_files),
                "limit_violations": len(limit_violations),
                "validation_status": "VALID" if is_valid else "INVALID",
            },
            color_override=color_override,
        )


# --------------------------------------------------------------------------
# Convenience entry point
# --------------------------------------------------------------------------

def run_algorithm(data: dict, params: Optional[AlgorithmParams] = None) -> Tuple[nx.DiGraph, List[AlgorithmState]]:
    G = build_graph(data)
    engine = BatchingAlgorithm(G, params)
    states = engine.run()
    return G, states
