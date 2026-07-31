from __future__ import annotations

import json


def write_batches_report(states, output_path: str):
    with open(output_path, "w") as f:
        for state in states:
            payload = {
                "step_name": state.step_name,
                "batch_count": len(state.batches),
                "batch_files": {
                    bid: list(info["files"]) for bid, info in state.batches.items()
                },
            }
            f.write(json.dumps(payload))
            f.write("\n")
    return output_path
