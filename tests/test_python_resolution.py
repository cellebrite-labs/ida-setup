"""Tests for resolve_python_for_cli in _common."""

import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from ida_setup._common import resolve_python_for_cli


def _make_exe(path: Path) -> Path:
    """Create a fake executable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class TestExplicitPath:
    def test_valid_exe(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path / "python3")
        result = resolve_python_for_cli(python_spec=str(exe), ida_app=None, verbose=False)
        assert result == exe.resolve()

    def test_tilde_expansion(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path / "python3")
        # Use the real path, just verifying expanduser + resolve doesn't crash.
        result = resolve_python_for_cli(python_spec=str(exe), ida_app=None, verbose=False)
        assert result.exists()

    def test_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="not found or not executable"):
            resolve_python_for_cli(python_spec=str(tmp_path / "no-such"), ida_app=None, verbose=False)

    def test_not_executable_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "python3"
        f.write_text("not executable")
        f.chmod(0o644)
        with pytest.raises(SystemExit, match="not found or not executable"):
            resolve_python_for_cli(python_spec=str(f), ida_app=None, verbose=False)


class TestIdaSpec:
    """Test --python ida. Requires mocking probe."""

    def _mock_probe_result(self, *, returncode: int, data: dict | None, tmpdir: Path):
        """Build a mock ProbeResult-like object."""
        from types import SimpleNamespace

        return SimpleNamespace(returncode=returncode, data=data, tmpdir=str(tmpdir))

    def test_successful_probe(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path / "python3")
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        probe_result = self._mock_probe_result(
            returncode=0,
            data={"sys.executable": str(exe), "is_venv": True},
            tmpdir=tmp_path / "artifacts",
        )
        (tmp_path / "artifacts").mkdir()

        with (
            patch("ida_setup._ida.resolve_ida_app", return_value=app),
            patch("ida_setup._probe.run_probe_once", return_value=probe_result),
        ):
            result = resolve_python_for_cli(python_spec="ida", ida_app=None, verbose=False)
        assert result == exe

    def test_no_venv_fails(self, tmp_path: Path) -> None:
        """When IDA is not using a venv, --python ida must fail."""
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        probe_result = self._mock_probe_result(
            returncode=0,
            data={
                "sys.executable": "/Applications/IDA Professional 9.3.app/Contents/MacOS/ida",
                "is_venv": False,
            },
            tmpdir=tmp_path / "artifacts",
        )
        (tmp_path / "artifacts").mkdir()

        with (
            patch("ida_setup._ida.resolve_ida_app", return_value=app),
            patch("ida_setup._probe.run_probe_once", return_value=probe_result),
        ):
            with pytest.raises(SystemExit, match="not using a venv"):
                resolve_python_for_cli(python_spec="ida", ida_app=None, verbose=False)

    def test_exe_not_python_fails(self, tmp_path: Path) -> None:
        """Even with is_venv=True, reject if sys.executable doesn't look like python."""
        exe = _make_exe(tmp_path / "ida")
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        probe_result = self._mock_probe_result(
            returncode=0,
            data={"sys.executable": str(exe), "is_venv": True},
            tmpdir=tmp_path / "artifacts",
        )
        (tmp_path / "artifacts").mkdir()

        with (
            patch("ida_setup._ida.resolve_ida_app", return_value=app),
            patch("ida_setup._probe.run_probe_once", return_value=probe_result),
        ):
            with pytest.raises(SystemExit, match="does not look like a Python"):
                resolve_python_for_cli(python_spec="ida", ida_app=None, verbose=False)

    def test_probe_fails(self, tmp_path: Path) -> None:
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        probe_result = self._mock_probe_result(returncode=1, data=None, tmpdir=tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir()

        with (
            patch("ida_setup._ida.resolve_ida_app", return_value=app),
            patch("ida_setup._probe.run_probe_once", return_value=probe_result),
        ):
            with pytest.raises(SystemExit, match="probe failed"):
                resolve_python_for_cli(python_spec="ida", ida_app=None, verbose=False)

    def test_probe_no_json(self, tmp_path: Path) -> None:
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        probe_result = self._mock_probe_result(returncode=0, data="not a dict", tmpdir=tmp_path / "artifacts")
        (tmp_path / "artifacts").mkdir()

        with (
            patch("ida_setup._ida.resolve_ida_app", return_value=app),
            patch("ida_setup._probe.run_probe_once", return_value=probe_result),
        ):
            with pytest.raises(SystemExit, match="did not produce JSON"):
                resolve_python_for_cli(python_spec="ida", ida_app=None, verbose=False)

    def test_probe_missing_sys_executable(self, tmp_path: Path) -> None:
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        probe_result = self._mock_probe_result(
            returncode=0, data={"other": "stuff", "is_venv": True}, tmpdir=tmp_path / "artifacts"
        )
        (tmp_path / "artifacts").mkdir()

        with (
            patch("ida_setup._ida.resolve_ida_app", return_value=app),
            patch("ida_setup._probe.run_probe_once", return_value=probe_result),
        ):
            with pytest.raises(SystemExit, match=r"missing sys\.executable"):
                resolve_python_for_cli(python_spec="ida", ida_app=None, verbose=False)

    def test_probe_exe_not_found(self, tmp_path: Path) -> None:
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        probe_result = self._mock_probe_result(
            returncode=0,
            data={"sys.executable": str(tmp_path / "python3-gone"), "is_venv": True},
            tmpdir=tmp_path / "artifacts",
        )
        (tmp_path / "artifacts").mkdir()

        with (
            patch("ida_setup._ida.resolve_ida_app", return_value=app),
            patch("ida_setup._probe.run_probe_once", return_value=probe_result),
        ):
            with pytest.raises(SystemExit, match="not an executable"):
                resolve_python_for_cli(python_spec="ida", ida_app=None, verbose=False)
