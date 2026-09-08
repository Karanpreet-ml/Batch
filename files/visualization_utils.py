"""
visualization_utils.py
------------------------
Turns an AlgorithmState (produced by algorithm_engine.py) into a Plotly
figure. The graph LAYOUT is computed once (outside of any single state) and
reused across every step so nodes don't jump around between steps — only
their color/visibility/position-within-community changes.
"""

from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

import networkx as nx
import plotly.graph_objects as go

from algorithm_engine import AlgorithmState, deterministic_token_count


def compute_base_layout(G: nx.DiGraph, seed: int = 42) -> Dict[str, Tuple[float, float]]:
    """One stable spring layout for the whole graph, reused across all steps."""
    undirected = G.to_undirected()
    pos = nx.spring_layout(undirected, seed=seed, k=1.6 / max(1, (len(G.nodes) ** 0.5)))
    return pos


def compute_community_layout(
    G: nx.DiGraph,
    base_pos: Dict[str, Tuple[float, float]],
    communities: Dict[str, Dict],
) -> Dict[str, Tuple[float, float]]:
    """Nudges nodes belonging to the same community toward a shared centroid,
    so communities visually cluster once detected, without fully discarding
    the base layout (keeps the animation feeling continuous)."""
    if not communities:
        return dict(base_pos)

    pos = dict(base_pos)
    for cid, info in communities.items():
        files = info["files"]
        if not files:
            continue
        cx = sum(base_pos[f][0] for f in files if f in base_pos) / len(files)
        cy = sum(base_pos[f][1] for f in files if f in base_pos) / len(files)
        for f in files:
            if f in base_pos:
                bx, by = base_pos[f]
                pos[f] = (bx * 0.45 + cx * 0.55, by * 0.45 + cy * 0.55)
    return pos


def build_figure(
    G: nx.DiGraph,
    state: AlgorithmState,
    pos: Dict[str, Tuple[float, float]],
    selected_node: Optional[str] = None,
    hover_neighbors: Optional[Set[str]] = set(),
) -> go.Figure:
    hidden = state.hidden_nodes
    visible_nodes = [n for n in G.nodes if n not in hidden]

    highlighted_set = set(state.highlighted_edges)
    hover_neighbors = hover_neighbors or set()

    # --- edges ---
    edge_x_normal, edge_y_normal = [], []
    edge_x_hi, edge_y_hi = [], []

    for u, v in G.edges:
        if u in hidden or v in hidden:
            continue
        if u not in pos or v not in pos:
            continue
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        is_highlighted = (u, v) in highlighted_set
        is_hover_related = selected_node is not None and (u == selected_node or v == selected_node)
        if is_highlighted or is_hover_related:
            edge_x_hi += [x0, x1, None]
            edge_y_hi += [y0, y1, None]
        else:
            edge_x_normal += [x0, x1, None]
            edge_y_normal += [y0, y1, None]

    edge_trace_normal = go.Scatter(
        x=edge_x_normal, y=edge_y_normal,
        line=dict(width=0.6, color="rgba(150,150,150,0.35)"),
        hoverinfo="none", mode="lines", showlegend=False,
    )
    edge_trace_hi = go.Scatter(
        x=edge_x_hi, y=edge_y_hi,
        line=dict(width=2.2, color="rgba(251,140,0,0.9)"),
        hoverinfo="none", mode="lines", showlegend=False,
    )

    # --- nodes ---
    node_x, node_y, node_color, node_text, node_size, node_line_width, node_line_color = (
        [], [], [], [], [], [], []
    )

    for n in visible_nodes:
        if n not in pos:
            continue
        x, y = pos[n]
        node_x.append(x)
        node_y.append(y)
        node_color.append(state.node_color.get(n, "#8ab4f8"))
        data = G.nodes[n]
        status = state.node_status.get(n, "reviewable")
        batch_id = None
        for bid, b in state.batches.items():
            if n in b["files"]:
                batch_id = bid
                break
            for cf in b["context_files"]:
                if n == cf:
                    batch_id = bid
                    break
            if batch_id is not None:
                batch_id = bid
                break
        token_count = data.get("token_count", deterministic_token_count(n))
        node_text.append(
            f"{n}<br>language: {data.get('language', 'unknown')}<br>"
            f"tokens: {token_count}<br>"
            f"imports: {data.get('import_count', 0)} | imported_by: {data.get('imported_by_count', 0)}<br>"
            f"status: {status}" + (f"<br>batch: {batch_id}" if batch_id else "")
        )
        base_size = 10 + min(14, token_count / 500)
        if n == selected_node:
            node_size.append(base_size + 8)
            node_line_width.append(3)
            node_line_color.append("#ffffff")
        elif n in hover_neighbors:
            node_size.append(base_size + 3)
            node_line_width.append(2)
            node_line_color.append("#ffffff")
        else:
            node_size.append(base_size)
            node_line_width.append(1)
            node_line_color.append("rgba(255,255,255,0.4)")

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers",
        hoverinfo="text", hovertext=node_text, text=visible_nodes,
        marker=dict(
            color=node_color, size=node_size,
            line=dict(width=node_line_width, color=node_line_color),
        ),
        showlegend=False,
    )

    fig = go.Figure(data=[edge_trace_normal, edge_trace_hi, node_trace])
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        height=650,
        clickmode="event+select",
        dragmode="pan",
    )
    return fig
