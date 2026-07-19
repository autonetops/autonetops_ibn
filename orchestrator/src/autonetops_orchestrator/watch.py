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

import yaml

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


def _released_from_hold(plan_dir: Path) -> bool:
    """A plan held for approval leaves the hold only when a manual dispatch
    produced a report that is not another missing-approvals abort. 'waiting'
    stays held: the human driving it re-runs with their approvals."""
    report_path = plan_dir / "report.yaml"
    if not report_path.exists():
        return False
    try:
        doc = yaml.safe_load(report_path.read_text()) or {}
    except Exception:  # noqa: BLE001 - unreadable report keeps the hold
        return False
    status, aborted = doc.get("status"), doc.get("aborted") or ""
    if status in ("succeeded", "failed"):
        return True
    return status == "aborted" and not aborted.startswith("missing approvals")


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
                try:
                    plan_dir, plan, _decision = plan_fn(branch)
                except Exception as exc:  # noqa: BLE001 - one bad branch or a
                    # broken pack must never kill the reconcile service; the
                    # failure is echoed every pass until someone fixes it,
                    # and planning retries next interval (self-healing).
                    echo(f"[watch] {name!r}: planning failed - {exc}")
                    state.pop(pc_id, None)  # leave no half-record behind
                    continue
                record["plan_dir"] = str(plan_dir) if plan_dir else None
                record["plan_id"] = plan.id if plan else None
                _save_state(state_path, state)

            elif pc_state == "merged" and not record.get("dispatched"):
                plan_dir = record.get("plan_dir")
                if plan_dir and record.get("approval_hold"):
                    # needs_approval is non-terminal: hold until a manual
                    # `dispatch --approve ...` leaves a real outcome behind
                    if _released_from_hold(Path(plan_dir)):
                        record["dispatched"] = True
                        record.pop("approval_hold", None)
                        echo(f"[watch] {name!r}: dispatched manually; hold released")
                        _save_state(state_path, state)
                    continue
                if plan_dir and not auto_dispatch:
                    # dispatch stays manual; announce once, keep undispatched
                    if not record.get("manual_hold"):
                        echo(f"[watch] {name!r} merged; auto-dispatch is off - "
                             f"run `ibn-orchestrate dispatch --plan-dir {plan_dir}`")
                        record["manual_hold"] = True
                        _save_state(state_path, state)
                    continue
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
                    # 3 = waiting on window, 4 = missing approvals: neither is
                    # terminal - a plan must never dead-end under automation
                    record["dispatched"] = code not in (3, 4)
                    record["dispatch_exit"] = code
                    if code == 3:
                        echo(f"[watch] {name!r}: window not open; will retry")
                    elif code == 4:
                        record["approval_hold"] = True
                        echo(f"[watch] {name!r}: plan needs approval - run "
                             f"`ibn-orchestrate dispatch --plan-dir {plan_dir} "
                             f"--approve <name>` (holding)")
                else:
                    record["dispatched"] = True  # planned as empty
                _save_state(state_path, state)

        if once:
            return
        sleep_fn(interval)
