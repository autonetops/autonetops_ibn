"""AutoNetOps IBN validator.

Turns ContractExpectations artifacts into verdicts against evidence the
executor collected. Pure logic: no device I/O, no Infrahub client - the
caller owns both sides of the comparison.
"""

from .gate import evaluate_sessions, failing_keys
from .models import CheckResult, ExpectationSet, GateResult, SessionExpectation

__version__ = "0.1.0"

__all__ = [
    "CheckResult",
    "ExpectationSet",
    "GateResult",
    "SessionExpectation",
    "evaluate_sessions",
    "failing_keys",
]
