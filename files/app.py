"""
app.py
-------
Streamlit UI layer. This file ONLY renders AlgorithmState snapshots produced
by algorithm_engine.py — it contains no batching logic itself.
"""

import json
import time

import streamlit as st

from algorithm_engine import AlgorithmParams, run_algorithm
from visualization_utils import build_figure, compute_base_layout, compute_community_layout
from batch_tools import (
    apply_custom_filter,
    compute_batch_health,
    compute_neighbor_overlap,
    export_snapshot,
    find_cross_community_duplicates,
    summarize_batches,
    top_n_largest_files,
)

st.set_page_config(page_title="File Batching Algorithm Visualizer", layout="wide")

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

# --------------------------------------------------------------------------
# Session state initialization
# --------------------------------------------------------------------------

def init_session():
    defaults = {
        "graph": None,
        "states": None,
        "base_pos": None,
        "current_step": 0,
        "selected_node": None,
        "playing": False,
        "params": AlgorithmParams(),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session()


def load_graph(data: dict):
    G, states = run_algorithm(data, st.session_state.params)
    st.session_state.graph = G
    st.session_state.states = states
    st.session_state.base_pos = compute_base_layout(G)
    st.session_state.current_step = 0
    st.session_state.selected_node = None


# --------------------------------------------------------------------------
# Sidebar: upload + algorithm steps
# --------------------------------------------------------------------------

with st.sidebar:
    st.title("Batching Algorithm")

    uploaded = st.file_uploader("Upload dependency graph JSON", type=["json"])

    with st.expander("Algorithm parameters"):
        max_files = st.number_input("Max files per batch", min_value=1, value=st.session_state.params.max_files_per_batch)
        max_tokens = st.number_input("Max tokens per batch", min_value=100, value=st.session_state.params.max_tokens_per_batch, step=500)
        min_files_comm = st.number_input("Min files per community (merge trigger)", min_value=1, value=st.session_state.params.min_files_per_community)
        max_context = st.number_input("Max context files per batch", min_value=0, value=st.session_state.params.max_context_files_per_batch)
        hub_threshold_auto = st.checkbox("Auto-detect hub threshold", value=st.session_state.params.hub_threshold is None)
        hub_threshold_manual = None
        if not hub_threshold_auto:
            hub_threshold_manual = st.number_input("Hub threshold (imported_by_count)", min_value=1, value=5)

        if st.button("Apply parameters & reload", use_container_width=True):
            st.session_state.params = AlgorithmParams(
                hub_threshold=None if hub_threshold_auto else int(hub_threshold_manual),
                max_files_per_batch=int(max_files),
                max_tokens_per_batch=int(max_tokens),
                min_files_per_community=int(min_files_comm),
                max_context_files_per_batch=int(max_context),
            )
            if uploaded is not None:
                data = json.loads(uploaded.getvalue())
                load_graph(data)
            elif "last_data" in st.session_state:
                load_graph(st.session_state.last_data)
            st.rerun()

    if uploaded is not None:
        data = json.loads(uploaded.getvalue())
        if st.session_state.get("last_uploaded_name") != uploaded.name:
            st.session_state.last_uploaded_name = uploaded.name
            st.session_state.last_data = data
            load_graph(data)

    st.divider()

    if st.session_state.states:
        with st.expander("Advanced tools"):
            filter_expr = st.text_input(
                "Custom filter expression",
                placeholder='e.g. imported_by_count > 5',
                key="filter_expr",
            )
            if st.button("Apply filter", use_container_width=True) and filter_expr:
                G = st.session_state.graph
                node_data = {n: G.nodes[n] for n in G.nodes}
                matches = apply_custom_filter(list(G.nodes), node_data, filter_expr)
                st.session_state["filter_matches"] = matches
            if "filter_matches" in st.session_state:
                st.caption(f"{len(st.session_state['filter_matches'])} file(s) matched")
                for f in st.session_state["filter_matches"][:20]:
                    st.write(f"- {f}")

            export_name = st.text_input("Export filename", value="snapshot.json", key="export_name")
            if st.button("Export current snapshot", use_container_width=True):
                current_state = st.session_state.states[st.session_state.current_step]
                path = export_snapshot(
                    {"step": current_state.step_name, "batches": current_state.batches},
                    export_name,
                )
                st.success(f"Saved to {path}")

    if st.session_state.states:
        st.caption("Algorithm steps")
        for i, name in enumerate(STEP_NAMES):
            label = f"{i}  {name}"
            if st.button(label, key=f"step_btn_{i}", use_container_width=True,
                         type="primary" if st.session_state.current_step == i else "secondary"):
                st.session_state.current_step = i
                st.session_state.playing = False
                st.rerun()


# --------------------------------------------------------------------------
# Main area
# --------------------------------------------------------------------------

st.markdown("## Dependency-Aware File Batching — Algorithm Visualizer")

if not st.session_state.states:
    st.info(
        "Upload a dependency graph JSON in the sidebar to begin. "
        "Expected format: `{\"nodes\": [...], \"edges\": [...]}` — "
        "see the README for a sample file."
    )
    st.stop()

states = st.session_state.states
current_step = st.session_state.current_step
state = states[current_step]
G = st.session_state.graph

# --- Top toolbar ---
toolbar = st.columns([1, 1, 1, 1, 1, 3])
with toolbar[0]:
    if st.button("Previous", use_container_width=True, disabled=current_step == 0):
        st.session_state.current_step = max(0, current_step - 1)
        st.rerun()
with toolbar[1]:
    if st.button("Next", use_container_width=True, disabled=current_step == len(states) - 1):
        st.session_state.current_step = min(len(states) - 1, current_step + 1)
        st.rerun()
with toolbar[2]:
    if st.button("Play", use_container_width=True):
        st.session_state.playing = True
with toolbar[3]:
    if st.button("Pause", use_container_width=True):
        st.session_state.playing = False
with toolbar[4]:
    if st.button("Restart", use_container_width=True):
        st.session_state.current_step = 0
        st.session_state.playing = False
        st.rerun()
with toolbar[5]:
    st.markdown(f"**Step {current_step} / {len(states) - 1} — {state.step_name}**")

# --- Layout: graph (left, ~70%) + right sidebar (details) ---
col_graph, col_details = st.columns([7, 3])

with col_graph:
    if current_step >= 4:
        pos = compute_community_layout(G, st.session_state.base_pos, state.communities)
    else:
        pos = st.session_state.base_pos

    hover_neighbors = set()
    if st.session_state.selected_node and st.session_state.selected_node in G.nodes:
        n = st.session_state.selected_node
        hover_neighbors = set(G.predecessors(n)) | set(G.successors(n))

    fig = build_figure(G, state, pos, selected_node=st.session_state.selected_node, hover_neighbors=hover_neighbors)

    event = st.plotly_chart(
        fig, use_container_width=True, key=f"graph_{current_step}",
        on_select="rerun", selection_mode="points",
    )

    if event and event.get("selection", {}).get("points"):
        pts = event["selection"]["points"]
        if pts:
            clicked_text = pts[0].get("text")
            if clicked_text:
                st.session_state.selected_node = clicked_text

with col_details:
    st.markdown("#### Details")
    sel = st.session_state.selected_node

    tabs = st.tabs(["File", "Community", "Batch"])

    with tabs[0]:
        if sel and sel in G.nodes:
            data = G.nodes[sel]
            status = state.node_status.get(sel, "reviewable")
            comm = None
            for cid, info in state.communities.items():
                if sel in info["files"]:
                    comm = cid
                    break
            batch = None
            context_of = []
            for bid, b in state.batches.items():
                if sel in b["files"]:
                    batch = bid
                if sel in b["context_files"]:
                    context_of.append(bid)
            st.write(f"**{sel}**")
            st.write(f"Language: {data['language']}")
            st.write(f"Import count: {data['import_count']}")
            st.write(f"Imported-by count: {data['imported_by_count']}")
            st.write(f"Token count: {data['token_count']}")
            st.write(f"Status: {status}")
            st.write(f"Community: {comm or '—'}")
            st.write(f"Batch: {batch or '—'}")
            if context_of:
                st.write(f"Serves as context for: {', '.join(context_of)}")
        else:
            st.caption("Click a node in the graph to see its details.")

    with tabs[1]:
        if state.communities:
            comm_ids = list(state.communities.keys())
            chosen = st.selectbox("Community", comm_ids, key=f"comm_select_{current_step}")
            info = state.communities[chosen]
            st.write(f"Community ID: {chosen}")
            st.write(f"Number of files: {info['num_files']}")
            st.write(f"Estimated tokens: {info['estimated_tokens']}")
            st.write("Why it exists: files in this group share dependency edges "
                      "detected by community detection, so they tend to change together.")
            with st.expander("Files in this community"):
                for f in info["files"]:
                    st.write(f"- {f}")
        else:
            st.caption("Communities appear from Step 4 onward.")

    with tabs[2]:
        if state.batches:
            batch_ids = list(state.batches.keys())
            chosen_b = st.selectbox("Batch", batch_ids, key=f"batch_select_{current_step}")
            b = state.batches[chosen_b]
            st.write(f"Batch ID: {chosen_b}")
            st.write(f"Total files: {b['total_files']}")
            st.write(f"Total tokens: {b['total_tokens']}")
            st.write(f"Validation: {b['validation']}")
            with st.expander("Files"):
                for f in b["files"]:
                    st.write(f"- {f}")
            if b["context_files"]:
                with st.expander("Context files"):
                    for f in b["context_files"]:
                        st.write(f"- {f}")
        else:
            st.caption("Batches appear from Step 7 onward.")

# --- Bottom explanation panel ---
st.divider()
exp = state.explanation
b1, b2, b3, b4 = st.columns(4)
with b1:
    st.markdown("**What happened?**")
    st.write(exp["what"])
with b2:
    st.markdown("**Why?**")
    st.write(exp["why"])
with b3:
    st.markdown("**What changed?**")
    st.write(exp["changed"])
with b4:
    st.markdown("**What happens next?**")
    st.write(exp["next"])

with st.expander("Step statistics"):
    st.json(state.stats)

# --- Final screen summary ---
if current_step == len(states) - 1:
    st.divider()
    st.markdown("### Final Summary")
    stats = state.stats
    cols = st.columns(4)
    labels = [
        ("Total Files", "total_files"), ("Filtered Files", "filtered_files"),
        ("Reviewable Files", "reviewable_files"), ("Hub Files", "hub_files"),
        ("Communities", "communities"), ("Final Batches", "final_batches"),
        ("Avg Batch Size", "average_batch_size"), ("Avg Tokens", "average_tokens"),
    ]
    for i, (label, key) in enumerate(labels):
        with cols[i % 4]:
            st.metric(label, stats.get(key, "—"))
    status = stats.get("validation_status", "UNKNOWN")
    if status == "VALID":
        st.success("Validation status: VALID — all batches satisfy every rule.")
    else:
        st.error(f"Validation status: {status} — see step statistics above for details.")

    with st.expander("Advanced batch analytics"):
        node_data = {n: G.nodes[n] for n in G.nodes}
        health = compute_batch_health(
            state.batches,
            st.session_state.params.max_files_per_batch,
            st.session_state.params.max_tokens_per_batch,
        )
        st.write("Batch health:", health)

        summary = summarize_batches(state.batches)
        st.write("Summary:", summary)

        largest = top_n_largest_files(node_data, n=5)
        st.write("Top largest files:", largest)

        dupes = find_cross_community_duplicates(state.communities)
        st.write("Cross-community duplicates:", dupes)

        sample_nodes = list(G.nodes)[:15]
        overlap = compute_neighbor_overlap(G, sample_nodes)
        st.write("Neighbor overlap (sample):", overlap)

# --- Auto-play ---
if st.session_state.playing:
    if current_step < len(states) - 1:
        time.sleep(1.4)
        st.session_state.current_step += 1
        st.rerun()
    else:
        st.session_state.playing = False