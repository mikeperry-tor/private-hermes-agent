"""Qualify desktop tool discovery against the configured SSH executor."""
import logging
import subprocess
import time

logger = logging.getLogger(__name__)
_PROBE_TIMEOUT_S = 4.0


def available(*, deadline=None):
    from tools.bot_desktop import placement, sandbox_host
    where = placement.resolve()
    if where.where != placement.TERMINAL:
        logger.info("Computer use unavailable: %s", where.reason)
        return False
    if deadline is None:
        deadline = time.monotonic() + sandbox_host._DISCOVERY_BUDGET_S
    try:
        env = placement.terminal_environment(create=True)
        if env is None:
            raise RuntimeError("SSH executor connection is unavailable")
        missing = sandbox_host.missing_binaries(
            env, extra=("cua-driver",), timeout=_PROBE_TIMEOUT_S, deadline=deadline)
        if missing:
            raise RuntimeError("executor image lacks " + ", ".join(missing) +
                               "; rebuild with COMPUTER_USE_ENABLED=true")
    except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as error:
        logger.info("Computer use unavailable: %s", error)
        return False
    return True
