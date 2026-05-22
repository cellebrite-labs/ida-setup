"""Subprocess runner and environment sanitization."""

import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)


_DIM = "\033[2m"
_RESET = "\033[0m"


def run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    text: bool = True,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    dim: bool = True,
) -> subprocess.CompletedProcess[str]:
    printable = shlex.join(cmd)
    LOG.debug("running: %s", printable)
    use_dim = dim and not capture and sys.stdout.isatty()
    if use_dim:
        sys.stdout.write(_DIM)
        sys.stdout.flush()
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=text,
            env=env,
            cwd=cwd,
        )
    finally:
        if use_dim:
            sys.stdout.write(_RESET)
            sys.stdout.flush()


def clean_env_for_python_exec() -> dict[str, str]:
    """Return a sanitized environment for running a specific python executable.

    Removes venv/python variables that could cause Python to resolve a
    different interpreter than the one explicitly invoked, and scrubs the
    venv bin directory from PATH.
    """
    env = dict(os.environ)

    venv = env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)

    if venv:
        venv_bin = Path(venv, "bin")
        path = env.get("PATH")
        if path:
            parts = [p for p in path.split(":") if p and Path(p).resolve() != venv_bin.resolve()]
            env["PATH"] = ":".join(parts)

    return env


def require_core_tools() -> None:
    """Fail fast if required command-line tools are not available on PATH."""
    required = ["launchctl", "mdfind", "open", "uv"]

    missing = [t for t in required if shutil.which(t) is None]
    if not missing:
        return

    path = os.environ.get("PATH", "")
    raise SystemExit(
        "required tool(s) missing: "
        + ", ".join(missing)
        + "\n\n"
        + f"PATH: {path}\n\n"
        + "These tools are required by ida-setup. Fix your PATH and re-run.\n"
        + "Expected on macOS: /usr/bin:/bin:/usr/sbin:/sbin (plus /opt/homebrew/bin for brew/uv)."
    )


def paths_equivalent(a: Path, b: Path) -> bool:
    """Check if two paths refer to the same filesystem entry."""
    try:
        if a.exists() and b.exists():
            return os.path.samefile(a, b)
    except Exception:
        pass
    try:
        return a.resolve() == b.resolve()
    except Exception:
        return str(a) == str(b)
