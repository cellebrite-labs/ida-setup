"""IDA probe: launch IDA and collect Python runtime diagnostics."""

import json
import logging
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ida_setup._common import _BOLD, _DIM, _GREEN, _RED, _style
from ida_setup._ida import IdaApp
from ida_setup._run import clean_env_for_python_exec, paths_equivalent, run

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProbeResult:
    tmpdir: Path
    out_json: Path
    ida_log: Path
    probe_script: Path
    cmd: list[str]
    returncode: int
    raw_json: str
    data: dict[str, object] | None


def write_probe_script(*, script_path: Path, out_json: Path, import_names: list[str]) -> None:
    """Generate the Python probe script that runs inside IDA."""
    imports_json = json.dumps(import_names)

    script = f"""\
import json
import os
import site
import sys
import traceback

OUT = r"{out_json}"
IMPORTS = {imports_json}

def _try_import(name: str):
    try:
        mod = __import__(name)
        return {{"ok": True, "file": getattr(mod, "__file__", None)}}
    except Exception as exc:
        return {{"ok": False, "error": repr(exc), "traceback": traceback.format_exc()}}


data = {{
  "sys.executable": sys.executable,
  "sys.version": sys.version,
  "sys.prefix": sys.prefix,
  "sys.base_prefix": getattr(sys, "base_prefix", None),
  "sys.path": list(sys.path),
  "is_venv": (getattr(sys, "base_prefix", sys.prefix) != sys.prefix),
  "imports": {{name: _try_import(name) for name in IMPORTS}},
  "env": {{
    "IDAPYTHON_VENV_EXECUTABLE": os.environ.get("IDAPYTHON_VENV_EXECUTABLE"),
    "PYTHONHOME": os.environ.get("PYTHONHOME"),
    "PYTHONPATH": os.environ.get("PYTHONPATH"),
  }},
}}

try:
    data["site.getsitepackages"] = site.getsitepackages()
except Exception:
    data["site.getsitepackages_error"] = traceback.format_exc()

try:
    data["site.getusersitepackages"] = site.getusersitepackages()
except Exception:
    data["site.getusersitepackages_error"] = traceback.format_exc()

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, sort_keys=True)

try:
    import idc
    idc.qexit(0)
except Exception:
    sys.exit(0)
"""

    script_path.write_text(script, encoding="utf-8")


def run_probe_once(
    *,
    app: IdaApp,
    import_names: list[str],
    announce: bool = False,
    print_cmd: bool = False,
) -> ProbeResult:
    """Launch IDA with a probe script and return the result."""
    input_path = Path("/bin/ls")

    tmpdir = Path(tempfile.mkdtemp(prefix="ida-setup-probe-"))
    out_json = tmpdir / "python_probe.json"
    ida_log = tmpdir / "ida.log"
    probe = tmpdir / "probe.py"

    write_probe_script(script_path=probe, out_json=out_json, import_names=import_names)

    args_list: list[str] = [
        "-A",
        f"-L{ida_log}",
        f"-S{probe}",
    ]

    out_idb = tmpdir / "probe.i64"
    args_list.append(f"-o{out_idb}")
    args_list.append(str(input_path))

    cmd = ["open", "-n", "-W", "-a", str(app.path), "--args", *args_list]

    if announce:
        print(f"opening {_style(_DIM, str(input_path))} in IDA")
    if print_cmd and (not LOG.isEnabledFor(logging.DEBUG)):
        print(f"running: {_style(_DIM, shlex.join(cmd))}", flush=True)

    # Use sanitized env so probe reflects IDA's own config, not the caller's shell.
    res = run(cmd, check=False, env=clean_env_for_python_exec())

    raw_json = ""
    data: dict[str, object] | None = None
    if out_json.exists():
        raw_json = out_json.read_text(encoding="utf-8", errors="replace")
        try:
            parsed = json.loads(raw_json)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed

    return ProbeResult(
        tmpdir=tmpdir,
        out_json=out_json,
        ida_log=ida_log,
        probe_script=probe,
        cmd=cmd,
        returncode=int(res.returncode),
        raw_json=raw_json,
        data=data,
    )


def run_probe(
    *,
    app: IdaApp,
    import_names: list[str],
    print_json: bool,
    expected_venv_python: Path | None = None,
) -> int:
    """Run probe, print summary, and optionally verify expected python."""
    result = run_probe_once(app=app, import_names=import_names, announce=True, print_cmd=print_json)

    if result.returncode != 0 or LOG.isEnabledFor(logging.DEBUG):
        code_style = _GREEN if result.returncode == 0 else _RED
        print(f"exit code: {_style(code_style, str(result.returncode))}")
    if result.returncode != 0:
        print(f"artifacts dir: {_style(_DIM, str(result.tmpdir))}")

    success = False
    try:
        if not result.out_json.exists():
            print(f"artifacts dir: {_style(_DIM, str(result.tmpdir))}")
            raise SystemExit(f"probe output missing: {result.out_json} (artifacts: {result.tmpdir})")

        raw = result.raw_json
        data = result.data

        if isinstance(data, dict):
            sys_exe = data.get("sys.executable")
            sys_prefix = data.get("sys.prefix")
            sys_base_prefix = data.get("sys.base_prefix")
            is_venv = data.get("is_venv")
            env = data.get("env") if isinstance(data.get("env"), dict) else {}
            venv_exe = env.get("IDAPYTHON_VENV_EXECUTABLE") if isinstance(env, dict) else None

            print(f"{_style(_BOLD, 'probe summary:')}")
            print(f"  sys.executable:  {_style(_DIM, str(sys_exe))}")
            print(f"  sys.prefix:      {_style(_DIM, str(sys_prefix))}")
            print(f"  sys.base_prefix: {_style(_DIM, str(sys_base_prefix))}")
            print(f"  is_venv:         {_style(_GREEN if is_venv else _RED, str(is_venv))}")
            print(f"  venv (env):      {_style(_DIM, str(venv_exe))}")

            imports = data.get("imports")
            if isinstance(imports, dict) and imports:
                print(f"{_style(_BOLD, 'imports:')}")
                for name, v in sorted(imports.items()):
                    if isinstance(v, dict) and v.get("ok") is True:
                        print(f"  {name}: {_style(_GREEN, 'found')}")
                    else:
                        err = None
                        if isinstance(v, dict):
                            err = v.get("error")
                        msg = _style(_RED, "NOT FOUND")
                        print(f"  {name}: {msg}" + (f" ({err})" if err else ""))

            if expected_venv_python is not None:
                got = str(sys_exe) if sys_exe is not None else ""
                want = str(expected_venv_python)
                if not paths_equivalent(Path(got), Path(want)):
                    raise SystemExit(
                        "probe indicates IDA is not using the expected venv python.\n"
                        f"expected: {want}\n"
                        f"got:      {got}\n"
                        f"artifacts: {result.tmpdir}"
                    )

        if print_json:
            print(_style(_DIM, "--- probe json ---"))
            print(raw.rstrip())

        if result.returncode != 0:
            raise SystemExit(f"probe failed (exit code {result.returncode}). artifacts: {result.tmpdir}")

        success = True
        return int(result.returncode)
    finally:
        if success:
            shutil.rmtree(result.tmpdir, ignore_errors=True)
