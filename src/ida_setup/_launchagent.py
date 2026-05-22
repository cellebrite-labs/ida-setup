"""LaunchAgent management for IDAPYTHON_VENV_EXECUTABLE."""

import logging
import os
import textwrap
import time
from pathlib import Path

from ida_setup._common import _DIM, _GREEN, PLIST_LABEL, PLIST_PATH, _style, confirm
from ida_setup._run import run

LOG = logging.getLogger(__name__)


def render_env_plist(venv_python: Path) -> str:
    """Render the LaunchAgent plist content."""
    return textwrap.dedent(
        f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key>
          <string>{PLIST_LABEL}</string>
          <key>RunAtLoad</key>
          <true/>
          <key>ProgramArguments</key>
          <array>
            <string>/bin/launchctl</string>
            <string>setenv</string>
            <string>IDAPYTHON_VENV_EXECUTABLE</string>
            <string>{venv_python}</string>
          </array>
        </dict>
        </plist>
        """
    )


def is_launch_agent_loaded() -> bool:
    domain = f"gui/{os.getuid()}"
    res = run(["launchctl", "print", f"{domain}/{PLIST_LABEL}"], check=False, capture=True)
    return bool(res.returncode == 0)


def is_launch_agent_up_to_date(venv_python_exe: Path) -> bool:
    if PLIST_PATH.exists():
        existing = PLIST_PATH.read_text(encoding="utf-8", errors="replace")
        if existing == render_env_plist(venv_python_exe):
            return True
    return False


def get_ida_venv_var() -> str:
    """Return the current IDAPYTHON_VENV_EXECUTABLE from launchctl, or ""."""
    res = run(
        ["launchctl", "asuser", str(os.getuid()), "launchctl", "getenv", "IDAPYTHON_VENV_EXECUTABLE"],
        check=False,
        capture=True,
    )
    if res.returncode != 0:
        return ""
    return (res.stdout or "").strip()


def install_launch_agent(*, venv_python_exe: Path) -> str:
    """Install and load the LaunchAgent. Return the env var value."""
    domain = f"gui/{os.getuid()}"

    ida_venv_var = get_ida_venv_var()
    if (
        is_launch_agent_loaded()
        and is_launch_agent_up_to_date(venv_python_exe)
        and ida_venv_var == str(venv_python_exe)
    ):
        if LOG.isEnabledFor(logging.DEBUG):
            print(_style(_DIM, "LaunchAgent already installed and up-to-date, skipping ..."))
        return ida_venv_var

    content = render_env_plist(venv_python_exe)

    if PLIST_PATH.exists():
        confirm(f"Overwrite LaunchAgent plist at {PLIST_PATH}?")
    else:
        confirm(f"Install LaunchAgent plist at {PLIST_PATH}?")

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(content, encoding="utf-8")

    bootout = run(
        ["launchctl", "bootout", domain, str(PLIST_PATH)],
        check=False,
        capture=True,
    )
    if bootout.returncode != 0:
        LOG.debug("launchctl bootout failed rc=%s stderr=%s", bootout.returncode, (bootout.stderr or "").strip())

    bootstrap = run(
        ["launchctl", "bootstrap", domain, str(PLIST_PATH)],
        check=False,
        capture=True,
    )
    if bootstrap.returncode != 0:
        msg = (bootstrap.stdout or "") + "\n" + (bootstrap.stderr or "")
        raise SystemExit("failed to load LaunchAgent via launchctl bootstrap. Output:\n" + msg.strip())

    ida_venv_var = get_ida_venv_var()
    for _ in range(5):
        if ida_venv_var == str(venv_python_exe):
            break
        time.sleep(0.25)
        ida_venv_var = get_ida_venv_var()

    if ida_venv_var != str(venv_python_exe):
        raise SystemExit(
            "LaunchAgent installed, but IDAPYTHON_VENV_EXECUTABLE not set as expected.\n"
            f"expected: {venv_python_exe}\n"
            f"found:    {ida_venv_var or '(not set)'}\n\n"
            "You may need to log out and log back in for the LaunchAgent to take effect."
        )

    print(_style(_GREEN, "LaunchAgent installed and loaded successfully."))
    return ida_venv_var
