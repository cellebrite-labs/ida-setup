"""Venv helpers: idapyswitch, idapro package install, activation, verification."""

import json
import logging
from pathlib import Path

from ida_setup._common import _BOLD, _DIM, _GREEN, _style
from ida_setup._ida import IdaApp
from ida_setup._run import clean_env_for_python_exec, run

LOG = logging.getLogger(__name__)

_PYTHON_CONFIG_SCRIPT = """\
import json
import sys
import sysconfig

json.dump(
    {
        "sys.base_prefix": getattr(sys, "base_prefix", sys.prefix),
        "PYTHONFRAMEWORK": sysconfig.get_config_var("PYTHONFRAMEWORK"),
    },
    sys.stdout,
)
"""


def _idalib_python_dir(app: IdaApp) -> Path:
    """Return the idalib/python directory inside the IDA app bundle."""
    d = app.bin_dir / "idalib" / "python"
    if not d.is_dir():
        raise SystemExit(
            f"idalib python directory not found: {d}\n"
            "This IDA installation may not include idalib support."
        )  # fmt: skip
    return d


def _py_activate_script(app: IdaApp) -> Path:
    """Return path to py-activate-idalib.py inside the IDA app bundle."""
    script = _idalib_python_dir(app) / "py-activate-idalib.py"
    if not script.is_file():
        raise SystemExit(f"py-activate-idalib.py not found: {script}")
    return script


def find_idapro_whl(idalib_python_dir: Path) -> Path | None:
    """Return the idapro .whl in the idalib python dir, if any (IDA >= 9.3)."""
    whls = sorted(idalib_python_dir.glob("idapro-*.whl"))
    return whls[-1] if whls else None


def _inspect_python(python_exe: Path) -> dict[str, object]:
    """Return framework-related metadata reported by the given interpreter."""
    res = run(
        [str(python_exe), "-c", _PYTHON_CONFIG_SCRIPT],
        check=False,
        capture=True,
        env=clean_env_for_python_exec(),
    )
    if res.returncode != 0:
        msg = (res.stdout or "") + "\n" + (res.stderr or "")
        raise SystemExit("failed to inspect Python interpreter. Output:\n" + msg.strip())

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("failed to parse Python inspection JSON") from exc

    if not isinstance(data, dict):
        raise SystemExit("Python inspection did not return a JSON object")

    return data


def _has_pyenv_framework_layout(base_prefix: Path) -> bool:
    """Return true if the base prefix has pyenv's framework build shape."""
    parts = base_prefix.parts
    return (
        len(parts) >= 7
        and parts[-7] == "versions"
        and parts[-5] == "Library"
        and parts[-4] == "Frameworks"
        and parts[-3] == "Python.framework"
        and parts[-2] == "Versions"
    )


def resolve_framework_python(python_exe: Path) -> Path:
    """Return the framework Python library for the given interpreter."""
    data = _inspect_python(python_exe)

    framework = data.get("PYTHONFRAMEWORK")
    base_prefix_raw = data.get("sys.base_prefix")
    if framework != "Python" or not isinstance(base_prefix_raw, str) or not base_prefix_raw:
        raise SystemExit(
            "not a framework Python.\n"
            f"python:            {python_exe}\n"
            f"PYTHONFRAMEWORK:   {framework or '(unknown)'}\n"
            f"sys.base_prefix:   {base_prefix_raw or '(unknown)'}\n\n"
            "Use a pyenv framework Python, for example:\n"
            '  ida-setup venv --python "$(pyenv which python)"'
        )

    base_prefix = Path(base_prefix_raw).resolve()
    framework_python = base_prefix / "Python"
    if base_prefix.parent.name != "Versions" or base_prefix.parent.parent.name != "Python.framework":
        raise SystemExit(
            "not using the expected Python.framework layout.\n"
            f"python:          {python_exe}\n"
            f"sys.base_prefix: {base_prefix}"
        )

    if not _has_pyenv_framework_layout(base_prefix):
        LOG.warning(
            "not using the expected pyenv framework layout; continuing because the "
            "framework library exists. python=%s sys.base_prefix=%s",
            python_exe,
            base_prefix,
        )

    if framework_python.is_file():
        return framework_python

    raise SystemExit(f"framework Python library not found.\npython:   {python_exe}\nexpected: {framework_python}")


def install_idapro_package(*, app: IdaApp, venv_python: Path) -> None:
    """pip install the idapro package from the IDA installation.

    IDA >= 9.3 ships a .whl file; older versions use setup.py.
    """
    idalib_python_dir = _idalib_python_dir(app)
    whl = find_idapro_whl(idalib_python_dir)

    if whl is not None:
        print(f"\n{_style(_BOLD, 'idalib:')} installing from {_style(_DIM, str(whl))}")
        run(
            ["uv", "pip", "install", "--upgrade", str(whl), "--python", str(venv_python)],
            env=clean_env_for_python_exec(),
        )
    elif (idalib_python_dir / "setup.py").is_file():
        print(f"\n{_style(_BOLD, 'idalib:')} installing from {_style(_DIM, str(idalib_python_dir))}")
        run(
            ["uv", "pip", "install", "--upgrade", ".", "--python", str(venv_python)],
            env=clean_env_for_python_exec(),
            cwd=str(idalib_python_dir),
        )
    else:
        raise SystemExit(
            f"No idapro wheel or setup.py found in {idalib_python_dir}\n"
            "This IDA installation may not include idalib Python support."
        )


def run_py_activate_idalib(*, app: IdaApp, venv_python: Path) -> None:
    """Run py-activate-idalib.py to configure ida-config.json.

    No -d/--ida-install-dir is passed: we always run the script in place from
    inside the target IDA installation, and the script self-detects its
    install dir from its own file location (two levels up from itself),
    which resolves to the same directory we'd otherwise compute ourselves.
    Relying on that avoids duplicating the vendor's own path logic here.
    """
    script = _py_activate_script(app)

    print(f"\n{_style(_BOLD, 'idalib:')} activating for {_style(_DIM, str(app.install_dir))}")
    run(
        [str(venv_python), str(script)],
        env=clean_env_for_python_exec(),
    )


def verify_idalib_import(venv_python: Path) -> None:
    """Verify that `import idapro` works in the venv."""
    res = run(
        [str(venv_python), "-c", "import idapro; print('ok')"],
        check=False,
        capture=True,
        env=clean_env_for_python_exec(),
    )
    if res.returncode != 0:
        msg = (res.stdout or "") + "\n" + (res.stderr or "")
        raise SystemExit(
            "idalib verification failed: `import idapro` did not succeed.\n\n"
            + msg.strip()
        )  # fmt: skip
    print(f"\n{_style(_BOLD, 'idalib:')} import idapro {_style(_GREEN, 'ok')}")
