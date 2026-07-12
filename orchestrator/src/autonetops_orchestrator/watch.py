"""The reconcile loop: follow Infrahub proposed changes.

"Webhooks trigger, reconciliation guarantees" (ADR-0004): this loop is the
guarantee half. Every pass it looks at ALL proposed changes, so a missed
event costs one interval, never a lost deployment.

  open    -> plan it (blast radius, timeline, decision - reviewable
             before anyone clicks merge)
  merged  -> dispatch the saved plan (windows still apply)

State (which PC produced which plan, what was dispatched) lives in a JSON
file next to the plans - restart-safe, inspection-friendly.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

PROPOSED_CHANGES_QUERY = """
query ProposedChanges {
  CoreProposedChange {
    edges {
      node {
        id
        name { value }
        state { value }
        source_branch { value }
        destination_branch { value }
      }
    }
  }
}
"""


def _load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2) + "\n")


def watch_loop(
    *,
    client,
    plan_fn: Callable[[str], tuple],  # branch -> (plan_dir, plan, decision)
    dispatch_fn: Callable[[Path], int],  # plan_dir -> exit code
    plans_dir: Path,
    interval: int = 15,
    once: bool = False,
    auto_dispatch: bool = True,
    echo: Callable[[str], None] = print,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    state_path = plans_dir / ".watch-state.json"
    plans_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(state_path)

    while True:
        result = client.execute_graphql(query=PROPOSED_CHANGES_QUERY)
        for edge in result["CoreProposedChange"]["edges"]:
            node = edge["node"]
            pc_id = node["id"]
            pc_state = node["state"]["value"]
            branch = node["source_branch"]["value"]
            name = node["name"]["value"]
            record = state.setdefault(pc_id, {"name": name, "branch": branch})

            if pc_state == "open" and "plan_dir" not in record:
                echo(f"[watch] proposed change {name!r} ({branch}) is open - planning")
                plan_dir, plan, _decision = plan_fn(branch)
                record["plan_dir"] = str(plan_dir) if plan_dir else None
                record["plan_id"] = plan.id if plan else None
                _save_state(state_path, state)

            elif pc_state == "merged" and not record.get("dispatched"):
                plan_dir = record.get("plan_dir")
                if plan_dir is None and "plan_dir" not in record:
                    # merged before we ever saw it open: plan from main vs
                    # itself is empty, so note it and move on - the change
                    # is already the deployed intent baseline.
                    echo(f"[watch] {name!r} merged before it was planned; "
                         f"reconcile pass will cover it")
                    record["plan_dir"] = None
                    record["dispatched"] = True
                elif plan_dir:
                    echo(f"[watch] {name!r} merged - dispatching {plan_dir}")
                    code = dispatch_fn(Path(plan_dir))
                    record["dispatched"] = code != 3  # 3 = waiting on window
                    record["dispatch_exit"] = code
                    if code == 3:
                        echo(f"[watch] {name!r}: window not open; will retry")
                else:
                    record["dispatched"] = True  # planned as empty
                _save_state(state_path, state)

        if once:
            return
        sleep_fn(interval)
