"""Parsers turning raw CLI output into structured facts.

Vendor parsing is driver territory (ADR-0011): the validator compares
expectations against facts, and must never see a vendor table. The tokenizer
below is deliberately shape-tolerant - EOS columns, SR Linux pipe tables and
FRR summaries all reduce to "a line with a peer IP and a state word".
"""

from __future__ import annotations

import re

_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

# Session states across vendors; "estab"/"established" normalize to the
# canonical form the validator matches on.
_STATES = {
    "idle", "connect", "active", "opensent", "openconfirm",
    "established", "estab",
}


def parse_bgp_neighbor_states(output: str) -> dict[str, str]:
    """{peer_ip: state} from any 'bgp summary/neighbor' style table.

    A line counts when it carries both an IPv4 token and a known state
    token; everything else (headers, router-id banners, borders) is noise.
    """
    neighbors: dict[str, str] = {}
    for line in output.splitlines():
        tokens = line.replace("|", " ").split()
        ip = next((t for t in tokens if _IPV4.match(t)), None)
        if not ip:
            continue
        state = next(
            (t for t in tokens if t.lower().strip("*()") in _STATES), None
        )
        if state is None:
            continue
        normalized = state.lower().strip("*()")
        neighbors[ip] = "established" if normalized.startswith("estab") else normalized
    return neighbors
