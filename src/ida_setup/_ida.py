"""IDA .app discovery and version parsing."""

import json
import logging
import os
import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ida_setup._common import _BOLD, _DIM, _GREEN, _YELLOW, _style, cfg
from ida_setup._run import clean_env_for_python_exec, paths_equivalent, run

LOG = logging.getLogger(__name__)

IDA_REG_PATH = Path.home() / ".idapro" / "ida.reg"


def read_python3_target_dll(reg_path: Path = IDA_REG_PATH) -> str | None:
    """Read Python3TargetDLL from IDA's binary registry (~/.idapro/ida.reg).

    idapyswitch persists the selected Python dylib path here.
    Returns the raw path string, or None if missing/unparseable.
    """
    try:
        data = reg_path.read_bytes()
    except (OSError, FileNotFoundError):
        return None

    key = b"Python3TargetDLL\x00"
    idx = data.find(key)
    if idx < 0:
        return None

    # Layout after key: uint32le length, uint8 type (1=string), then <length> bytes.
    hdr = idx + len(key)
    if hdr + 5 > len(data):
        return None

    length = int.from_bytes(data[hdr : hdr + 4], "little")
    if data[hdr + 4] != 1 or length <= 0 or hdr + 5 + length > len(data):
        return None

    try:
        return data[hdr + 5 : hdr + 5 + length].decode("utf-8")
    except UnicodeDecodeError:
        return None


IDA_CONFIG_PATH = Path.home() / ".idapro" / "ida-config.json"


def read_ida_config_install_dir(config_path: Path = IDA_CONFIG_PATH) -> Path | None:
    """Read Paths.ida-install-dir from ida-config.json (written by py-activate-idalib)."""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        val = data["Paths"]["ida-install-dir"]
        if not isinstance(val, str) or not val:
            return None
        return Path(val)
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None


@dataclass(frozen=True)
class IdaApp:
    path: Path
    version: tuple[int, ...]

    @property
    def install_dir(self) -> Path:
        """The IDA binaries directory (what py-activate-idalib stores)."""
        if sys.platform == "darwin":
            return self.path / "Contents" / "MacOS"
        return self.path

    @property
    def idapyswitch(self) -> Path:
        """Path to the idapyswitch binary for this IDA installation."""
        return self.install_dir / "idapyswitch"


def switch_idapython(*, app: IdaApp, python_library: Path) -> None:
    """Run idapyswitch so UI IDA uses the given Python library."""
    if not (app.idapyswitch.is_file() and os.access(app.idapyswitch, os.X_OK)):
        raise SystemExit(f"idapyswitch not found or not executable: {app.idapyswitch}")

    print(f"\n{_style(_BOLD, 'idapython:')} switching to {_style(_DIM, str(python_library))}")
    res = run(
        [str(app.idapyswitch), "--force-path", str(python_library)],
        check=False,
        capture=True,
        env=clean_env_for_python_exec(),
    )
    if res.returncode != 0:
        msg = (res.stdout or "") + "\n" + (res.stderr or "")
        raise SystemExit("idapyswitch failed. Output:\n" + msg.strip())

    selected = read_python3_target_dll()
    if selected and paths_equivalent(Path(selected), python_library):
        print(f"{_style(_BOLD, 'idapython:')} idapyswitch {_style(_GREEN, 'ok')}")
        return

    raise SystemExit(
        "idapyswitch did not persist the expected Python library.\n"
        f"expected: {python_library}\n"
        f"found:    {selected or '(unknown)'}"
    )


def mdfind_ida_apps() -> list[Path]:
    """Return IDA .app bundles discovered via Spotlight (mdfind)."""
    res = subprocess.run(
        ["mdfind", "kMDItemFSName == 'IDA Professional*.app'"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if res.returncode != 0:
        err = (res.stderr or "").strip()
        raise SystemExit(
            "mdfind failed while searching for IDA installations. "
            "Pass --ida explicitly.\n" + (f"mdfind stderr: {err}" if err else "")
        )

    out: list[Path] = []
    for line in res.stdout.splitlines():
        p = Path(line.strip())
        if p.suffix == ".app" and p.exists():
            out.append(p)

    if not out:
        raise SystemExit(
            "No IDA Professional .app bundles found via Spotlight. "
            "Install IDA or pass --ida '/Applications/IDA Professional X.Y.app'."
        )

    return sorted(set(out))


def read_ida_app_version(app_path: Path) -> tuple[int, ...]:
    """Parse IDA version from the app bundle's Info.plist."""
    info_plist = app_path / "Contents" / "Info.plist"
    try:
        with info_plist.open("rb") as f:
            data = plistlib.load(f)
    except Exception as exc:
        raise SystemExit(f"failed to read Info.plist: {info_plist} ({exc})") from exc

    ver = data.get("CFBundleShortVersionString")
    if not isinstance(ver, str) or not ver.strip():
        raise SystemExit(f"missing CFBundleShortVersionString in Info.plist: {info_plist}")

    ver = ver.strip()
    m = re.match(r"^([0-9]+(?:\.[0-9]+)*)", ver)
    if not m:
        raise SystemExit(f"invalid CFBundleShortVersionString in Info.plist: {info_plist} (value: {ver!r})")

    return tuple(int(x) for x in m.group(1).split("."))


def choose_ida_app(apps: list[IdaApp]) -> IdaApp:
    """Pick an IDA installation from a list of candidates (newest first)."""
    if not apps:
        raise SystemExit(
            "Could not find any 'IDA Professional*.app' via Spotlight. "
            "Pass --ida '/Applications/IDA Professional X.Y.app'."
        )

    if len(apps) == 1:
        return apps[0]

    default = apps[0]

    if LOG.isEnabledFor(logging.DEBUG) and sys.stdin.isatty() and not cfg.yes:
        print(_style(_YELLOW, "Multiple IDA installations found; auto-selecting newest. Use --ida to pin:"))
        for a in apps:
            ver = ".".join(str(x) for x in a.version)
            print(f"  - {a.path} {_style(_DIM, f'(version: {ver})')}")
        print()

    return default


def resolve_ida_app(explicit: str | None) -> IdaApp:
    """Resolve which IDA .app bundle to use.

    If `explicit` is provided, validates it. Otherwise, discovers via Spotlight
    and selects the newest.
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.exists() or p.suffix != ".app":
            raise SystemExit(f"IDA app not found or not a .app bundle: {p}")
        ver = read_ida_app_version(p)
        return IdaApp(path=p, version=ver)

    paths = mdfind_ida_apps()
    apps: list[IdaApp] = []
    errors: list[str] = []

    for p in paths:
        try:
            ver = read_ida_app_version(p)
        except SystemExit as exc:
            errors.append(f"{p}: {exc}")
            continue
        apps.append(IdaApp(path=p, version=ver))

    if not apps:
        msg = "\n".join(f"- {x}" for x in errors) if errors else "(none)"
        raise SystemExit(
            "IDA installations found via Spotlight, but none could be version-parsed from Info.plist.\n"
            + msg
            + "\n\nPass --ida explicitly."
        )

    if errors:
        msg = "\n".join(f"- {x}" for x in errors)
        LOG.warning(
            "Skipping IDA installations with unreadable/unparseable Info.plist versions:\n%s",
            msg,
        )

    apps.sort(key=lambda a: a.version, reverse=True)
    return choose_ida_app(apps)
