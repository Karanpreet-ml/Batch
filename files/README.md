# File Batching Algorithm Visualizer

An interactive Streamlit app that visualizes, step by step, how a
dependency-aware file batching algorithm turns an arbitrary code
dependency graph into optimized review batches.

## Architecture

```
algorithm_engine.py     Pure Python. Parses the graph, runs the 10-step
                        algorithm, and produces a list of AlgorithmState
                        snapshots. Knows nothing about Streamlit.

visualization_utils.py  Turns an AlgorithmState + a stable node layout into
                        a Plotly figure. Also knows nothing about Streamlit
                        session state.

app.py                  Streamlit UI only. Renders whichever AlgorithmState
                        is currently selected; handles Previous/Next/Play/
                        Pause/Restart, node selection, and the details panels.
```

Because the algorithm runs once per upload and produces a full list of
snapshots up front, navigating between steps (Previous/Next/jumping to a
step in the sidebar) is just an index change — no recomputation.

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).

## Input format

Upload a JSON file shaped like this:

```json
{
  "nodes": [
    {
      "file_path": "src/auth/login.py",
      "language": "python",
      "import_count": 3,
      "imported_by_count": 2,
      "token_count": 1450
    }
  ],
  "edges": [
    { "source": "src/auth/login.py", "target": "src/core/database.py" }
  ]
}
```

- `token_count` is optional — if omitted, a deterministic pseudo-random
  value is generated from the file path (same file always gets the same
  token count across runs).
- `sample_graph.json` is included for a quick first run — a small,
  synthetic 23-file project with hubs, isolated scripts, and clusters
  by feature area (auth, billing, reports, notifications, frontend).

## What each step does

| # | Step | Purpose |
|---|------|---------|
| 0 | Fetch & Filter | Drop generated/config/doc/unsupported files |
| 1 | Hub Detection | Flag heavily-imported files as shared context |
| 2 | Isolated Nodes | Set aside files with no dependency relationships |
| 3 | Working Graph | Build the graph community detection will run on |
| 4 | Community Detection | Louvain clustering of the working graph |
| 5 | Recursive Split | Bisect communities that exceed size/token limits |
| 6 | Merge Consolidation | Merge small communities into connected neighbors |
| 7 | Context Injection | Attach relevant hub files to each batch |
| 8 | Isolated Packing | Pack isolated files into batches that still fit |
| 9 | Validation | Confirm every file is assigned exactly once, no limit is broken |

## Adjustable parameters (sidebar)

- Max files per batch
- Max tokens per batch
- Min files per community (below this, a community is a merge candidate)
- Max context files attached per batch
- Hub threshold (auto-detected via mean + 2·stddev of `imported_by_count`,
  or set manually)

## Notes

- Works on graphs from a handful of files up to 1000+ (tested at 1200
  nodes; full algorithm run completes in a couple of seconds).
- Every color, count, and grouping shown in the UI is derived from your
  uploaded graph — nothing is hardcoded.
