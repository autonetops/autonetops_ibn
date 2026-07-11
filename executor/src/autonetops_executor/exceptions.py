class ExecutorError(Exception):
    """Base for all executor failures."""


class UnsupportedCapability(ExecutorError):
    """A verb was invoked that this driver's capability matrix does not declare."""


class UnknownDriver(ExecutorError):
    """No driver registered under the requested name."""


class ChangeNotFound(ExecutorError):
    """confirm()/rollback() referenced a change_id the driver does not know."""


class RollbackFailed(ExecutorError):
    """Rollback did not restore the pre-change state. Highest-severity failure:
    the orchestrator must abort the plan and page a human."""
