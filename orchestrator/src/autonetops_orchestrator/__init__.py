"""AutoNetOps IBN orchestrator.

The workflow role (ADR-0010) as a plain, independently runnable library:
plan -> evaluate timeline (SoT change windows) -> decide -> dispatch.
Prefect flows (orchestrator/flows/) will wrap these functions; nothing in
here imports Prefect (ADR-0005).
"""

from .dispatch import DispatchOptions, DispatchReport, dispatch_plan
from .render_source import RenderedArtifactSource
from .strategy import Decision, apply_to_plan, decide
from .timeline import Timeline, evaluate_timeline
from .windows import ChangeWindow, active_freezes, load_windows, next_slot

__version__ = "0.1.0"

__all__ = [
    "ChangeWindow",
    "Decision",
    "DispatchOptions",
    "DispatchReport",
    "RenderedArtifactSource",
    "Timeline",
    "active_freezes",
    "apply_to_plan",
    "decide",
    "dispatch_plan",
    "evaluate_timeline",
    "load_windows",
    "next_slot",
]
