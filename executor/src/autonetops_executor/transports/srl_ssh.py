"""SR Linux SSH CLI transport (netmiko ``nokia_srl``).

Hard-won containerlab lessons encoded here:

- SR Linux's two-line prompt + ANSI output makes netmiko's echo verification
  flaky, so every command goes through ``send_command_timing``.
- On a busy box the first command after login can get merged with netmiko's
  session-prep lines and silently never execute. Entering candidate mode is
  therefore VERIFIED against the ``--{ <mode> }--`` banner and retried.
- The named private candidate persists across SSH sessions; a failed push
  leaves it dirty and poisons the next one. Always ``discard stay`` first.
"""

from __future__ import annotations

import time
from typing import Any

from ..exceptions import ExecutorError

ERROR_MARKERS = ("error", "unknown token", "invalid value", "failed")

FACTORY_PASSWORD = "NokiaSrl1!"


class SrlSsh:
    """One SSH CLI session against one SR Linux box."""

    def __init__(self, connection: dict[str, Any]):
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ExecutorError(
                "netmiko not installed; use `pip install autonetops-executor[cli]`"
            ) from exc

        host = connection["host"]
        username = connection.get("username", "admin")
        passwords = [connection.get("password", "admin")]
        # containerlab ships SR Linux with a factory password; tolerate a box
        # that has not converged onto the managed credential yet
        if FACTORY_PASSWORD not in passwords:
            passwords.append(FACTORY_PASSWORD)

        last_exc: Exception | None = None
        self._conn = None
        for password in passwords:
            try:
                self._conn = ConnectHandler(
                    device_type="nokia_srl", host=host,
                    username=username, password=password,
                    port=connection.get("port", 22),
                )
                break
            except Exception as exc:  # noqa: BLE001 - try next credential
                last_exc = exc
        if self._conn is None:
            raise ExecutorError(f"SSH authentication failed for {username}@{host}: {last_exc}")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.disconnect()
            self._conn = None

    def __enter__(self) -> "SrlSsh":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- primitives -----------------------------------------------------------

    def run(self, command: str) -> str:
        return self._conn.send_command_timing(command)

    def mode_banner(self) -> str:
        """SR Linux prints a ``--{ <mode> }--[ <context> ]--`` banner above
        every prompt; a bare newline is the cheapest way to read it."""
        self._conn.write_channel("\n")
        time.sleep(0.7)
        return self._conn.read_channel()

    def enter_candidate(self, attempts: int = 3) -> None:
        self.mode_banner()  # settle the channel first
        for _ in range(attempts):
            self.run("enter candidate private")
            if "candidate" in self.mode_banner():
                self.run("discard stay")  # drop leftovers from failed pushes
                return
            time.sleep(1)
        raise ExecutorError("could not enter SR Linux candidate mode")

    def source_lines(self, lines: list[str]) -> str:
        """Feed set-lines into the current candidate; raise on any parse error."""
        output = ""
        for line in lines:
            if not line.strip() or line.startswith("#"):
                continue
            output += self.run(line)
        low = output.lower()
        if any(m in low for m in ERROR_MARKERS):
            self.run("discard stay")
            raise ExecutorError(f"candidate rejected:\n{output.strip()[-800:]}")
        return output

    def diff(self) -> str:
        return self.run("diff")

    def discard(self) -> None:
        self.run("discard stay")

    def commit_save(self) -> str:
        output = self.run("commit save")
        if "committed" not in output.lower():
            raise ExecutorError(f"no commit confirmation:\n{output.strip()[-400:]}")
        return output

    def running_config_flat(self) -> str:
        """The running config as `set` lines - stable input for checksums."""
        return self.run("info flat from running")

    def generate_checkpoint(self, name: str) -> str:
        output = self.run(f"tools system configuration generate-checkpoint name {name}")
        if "generated checkpoint" not in output.lower():
            raise ExecutorError(f"checkpoint not confirmed:\n{output.strip()[-400:]}")
        return output

    def revert_checkpoint(self, name: str) -> str:
        output = self.run(f"tools system configuration checkpoint {name} revert")
        low = output.lower()
        if any(m in low for m in ERROR_MARKERS):
            raise ExecutorError(f"checkpoint revert failed:\n{output.strip()[-400:]}")
        self.run("save startup")
        return output
