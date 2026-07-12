"""Derive a plan's business priority from the SoT.

The plan itself is mechanism - which artifacts change where. Its URGENCY
belongs to the intent layer: whichever intents' contracts run on the
changed devices lend the plan their priority (highest wins). Nothing here
is typed by hand at dispatch time.
"""

from __future__ import annotations

PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

CONTRACT_DEVICES_QUERY = """
query ContractPriorities {
  IntentRoutingContract {
    edges {
      node {
        name { value }
        pe_devices { edges { node { name { value } } } }
        ce_devices { edges { node { name { value } } } }
        policy {
          node {
            intent {
              node {
                name { value }
                priority { value }
              }
            }
          }
        }
      }
    }
  }
}
"""


def intent_priority_for(client, devices: set[str], branch: str = "main") -> tuple[str, list[str]]:
    """(highest priority, [intents that set it]) for contracts touching
    ``devices``; medium when nothing matches."""
    result = client.execute_graphql(query=CONTRACT_DEVICES_QUERY, branch_name=branch)
    best, sources = "medium", []
    for edge in result["IntentRoutingContract"]["edges"]:
        node = edge["node"]
        members = {
            e["node"]["name"]["value"]
            for side in ("pe_devices", "ce_devices")
            for e in (node.get(side) or {}).get("edges", [])
        }
        if not members & devices:
            continue
        intent = (((node.get("policy") or {}).get("node") or {})
                  .get("intent") or {}).get("node") or {}
        priority = (intent.get("priority") or {}).get("value") or "medium"
        intent_name = (intent.get("name") or {}).get("value") or "unknown"
        if PRIORITY_ORDER.get(priority, 1) > PRIORITY_ORDER.get(best, 1):
            best, sources = priority, [intent_name]
        elif priority == best and intent_name not in sources:
            sources.append(intent_name)
    return best, sources
