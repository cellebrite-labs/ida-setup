"""Shared constants, configuration, venv helpers, and python resolution."""

import logging
import os
import shutil
import sys
from pathlib import Path

from ida_setup._run import clean_env_for_python_exec, run

LOG = logging.getLogger("ida_setup")


# -- ANSI styling ------------------------------------------------------------

_BOLD = "1"
_DIM = "2"
_RED = "31"
_GREEN = "32"
_YELLOW = "33"
_BOLD_GREEN = "1;32"
_CYAN = "36"


def _use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _style(code: str, text: str) -> str:
    if not _use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


# -- Constants ---------------------------------------------------------------

VENV_DIR = Path(os.path.expanduser("~/.idapro/venv"))

PLIST_LABEL = "com.cellebrite.ida-setup.env"
PLIST_PATH = Path(os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_LABEL}.plist"))

PLUGINS_DIR = Path.home() / ".idapro" / "plugins"
LOADERS_DIR = Path.home() / ".idapro" / "loaders"


# -- Global runtime config (set once by CLI, read everywhere) ----------------


class RunCfg:
    yes: bool = False


cfg = RunCfg()


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def non_interactive_without_yes() -> bool:
    """True if running non-interactively without --yes (can't prompt, no consent given)."""
    return not cfg.yes and not sys.stdin.isatty()


def confirm(prompt: str) -> None:
    """Prompt user for confirmation; raise SystemExit on rejection."""
    if cfg.yes:
        return
    if non_interactive_without_yes():
        raise SystemExit("non-interactive session; pass --yes to proceed")

    ans = input(f"CONFIRM: {prompt} [y/N] ").strip().lower()
    if ans not in {"y", "yes"}:
        raise SystemExit("aborted")


def require_macos() -> None:
    if sys.platform != "darwin":
        raise SystemExit("ida-setup currently supports macOS only")


# -- Venv helpers ------------------------------------------------------------


def get_venv_python_exe() -> Path | None:
    if not VENV_DIR.exists():
        return None
    exe = VENV_DIR / "bin" / "python3"
    if exe.exists():
        return exe
    return None


def read_pyvenv_cfg(venv_dir: Path = VENV_DIR) -> dict[str, str] | None:
    """Read <venv>/pyvenv.cfg as a key=value map."""
    cfg_path = venv_dir / "pyvenv.cfg"
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return None
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv[k.strip()] = v.strip()
    return kv


def resolve_base_prefix(venv_dir: Path = VENV_DIR) -> Path | None:
    """Resolve the base Python installation prefix for a venv.

    Reads pyvenv.cfg 'home' (base python's bin dir), resolves symlinks,
    and returns the parent directory.
    """
    pyvenv = read_pyvenv_cfg(venv_dir)
    if not pyvenv:
        return None
    home = pyvenv.get("home")
    if not home:
        return None
    p = Path(home)
    resolved = p.resolve() if p.exists() else p
    return resolved.parent


def run_pip(*, python_exe: Path, pip_args: list[str]) -> int:
    """Run uv pip with the given interpreter."""
    res = run(
        ["uv", "pip", *pip_args, "--python", str(python_exe)],
        check=False,
        env=clean_env_for_python_exec(),
        dim=False,
    )
    return int(res.returncode)


# -- Python resolution ------------------------------------------------------

_VENV_SETUP_HINT = (
    "Set up a venv first:\n"
    "  ida-setup venv --python /path/to/python3"
)  # fmt: skip


def _looks_like_python(path: Path) -> bool:
    """True if the filename looks like a Python interpreter, not a host app."""
    return "python" in path.name.lower()


def resolve_python_for_cli(
    *,
    python_spec: str,
    ida_app: str | None,
    verbose: bool,
) -> Path:
    """Resolve the Python interpreter to use for pip/python subcommands."""
    from ida_setup._ida import resolve_ida_app
    from ida_setup._probe import run_probe_once

    if python_spec == "ida":
        app = resolve_ida_app(ida_app)

        result = run_probe_once(app=app, import_names=[], announce=True, print_cmd=verbose)
        if result.returncode != 0:
            raise SystemExit(
                "--python ida: probe failed.\n"
                f"ida:        {app.path}\n"
                f"exit code:  {result.returncode}\n"
                f"artifacts:  {result.tmpdir}"
            )

        data = result.data
        if not isinstance(data, dict):
            raise SystemExit(f"--python ida: probe did not produce JSON data. artifacts: {result.tmpdir}")

        is_venv = data.get("is_venv", False)
        if not is_venv:
            shutil.rmtree(result.tmpdir, ignore_errors=True)
            raise SystemExit(
                "--python ida: IDA is not using a venv.\n"
                "When no venv is active, sys.executable reports the IDA binary,\n"
                "not a Python interpreter.\n\n" + _VENV_SETUP_HINT
            )

        sys_exe = data.get("sys.executable")

        if not isinstance(sys_exe, str) or not sys_exe.strip():
            raise SystemExit(f"--python ida: probe JSON missing sys.executable. artifacts: {result.tmpdir}")

        python_exe = Path(sys_exe)

        if not _looks_like_python(python_exe):
            shutil.rmtree(result.tmpdir, ignore_errors=True)
            raise SystemExit(
                "--python ida: sys.executable does not look like a Python interpreter.\n"
                f"sys.executable: {python_exe}\n\n"
                "IDA may not have properly activated the venv.\n"
                "Use an explicit path instead:\n"
                "  --python /path/to/python3"
            )

        if not (python_exe.exists() and os.access(python_exe, os.X_OK)):
            raise SystemExit(
                "--python ida: probed sys.executable is not an executable file.\n"
                f"sys.executable: {python_exe}\n"
                f"artifacts:      {result.tmpdir}"
            )

        shutil.rmtree(result.tmpdir, ignore_errors=True)

        if verbose:
            print(f"--python ida: using {_style(_DIM, str(python_exe))}")

        return python_exe

    # Explicit path.
    python_exe = Path(python_spec).expanduser().resolve()
    if not (python_exe.exists() and os.access(python_exe, os.X_OK)):
        raise SystemExit(f"--python: python executable not found or not executable: {python_exe}")

    if verbose:
        print(f"--python {python_exe}: using {_style(_DIM, 'explicit interpreter')}")

    return python_exe
