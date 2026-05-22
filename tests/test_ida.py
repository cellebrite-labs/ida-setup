"""Tests for _ida module: version parsing."""

import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ida_setup._ida import IdaApp, choose_ida_app, read_ida_app_version, switch_idapython


def _make_exe(path: Path) -> Path:
    """Create a fake executable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class TestReadIdaAppVersion:
    def test_valid_plist(self, tmp_path: Path) -> None:
        import plistlib

        app = tmp_path / "IDA Professional 9.2.app"
        contents = app / "Contents"
        contents.mkdir(parents=True)
        info = contents / "Info.plist"
        with info.open("wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "9.2.0"}, f)

        assert read_ida_app_version(app) == (9, 2, 0)

    def test_two_component_version(self, tmp_path: Path) -> None:
        import plistlib

        app = tmp_path / "IDA.app"
        contents = app / "Contents"
        contents.mkdir(parents=True)
        info = contents / "Info.plist"
        with info.open("wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "9.2"}, f)

        assert read_ida_app_version(app) == (9, 2)

    def test_missing_plist(self, tmp_path: Path) -> None:
        app = tmp_path / "IDA.app"
        app.mkdir()
        (app / "Contents").mkdir()
        with pytest.raises(SystemExit, match=r"failed to read Info\.plist"):
            read_ida_app_version(app)

    def test_missing_version_key(self, tmp_path: Path) -> None:
        import plistlib

        app = tmp_path / "IDA.app"
        contents = app / "Contents"
        contents.mkdir(parents=True)
        info = contents / "Info.plist"
        with info.open("wb") as f:
            plistlib.dump({"CFBundleName": "IDA"}, f)

        with pytest.raises(SystemExit, match="missing CFBundleShortVersionString"):
            read_ida_app_version(app)

    def test_invalid_version_string(self, tmp_path: Path) -> None:
        import plistlib

        app = tmp_path / "IDA.app"
        contents = app / "Contents"
        contents.mkdir(parents=True)
        info = contents / "Info.plist"
        with info.open("wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "beta"}, f)

        with pytest.raises(SystemExit, match="invalid CFBundleShortVersionString"):
            read_ida_app_version(app)


class TestSwitchIdapython:
    def test_runs_idapyswitch_force_path(self, tmp_path: Path) -> None:
        python_library = tmp_path / "python" / "Python.framework" / "Versions" / "3.12" / "Python"
        python_library.parent.mkdir(parents=True)
        python_library.touch()

        app_path = tmp_path / "IDA.app"
        idapyswitch = _make_exe(app_path / "Contents" / "MacOS" / "idapyswitch")
        app = IdaApp(path=app_path, version=(9, 3))

        with (
            patch("ida_setup._ida.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch("ida_setup._ida.read_python3_target_dll", return_value=str(python_library)),
        ):
            switch_idapython(app=app, python_library=python_library)

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == [str(idapyswitch), "--force-path", str(python_library)]

    def test_fails_when_registry_does_not_match(self, tmp_path: Path) -> None:
        python_library = tmp_path / "python" / "Python.framework" / "Versions" / "3.12" / "Python"
        python_library.parent.mkdir(parents=True)
        python_library.touch()

        app_path = tmp_path / "IDA.app"
        _make_exe(app_path / "Contents" / "MacOS" / "idapyswitch")
        app = IdaApp(path=app_path, version=(9, 3))

        with (
            patch("ida_setup._ida.run", return_value=MagicMock(returncode=0)),
            patch("ida_setup._ida.read_python3_target_dll", return_value=str(tmp_path / "other" / "Python")),
        ):
            with pytest.raises(SystemExit, match="did not persist"):
                switch_idapython(app=app, python_library=python_library)


class TestChooseIdaApp:
    def test_single_app(self) -> None:
        app = IdaApp(path=Path("/app/IDA.app"), version=(9, 2))
        assert choose_ida_app([app]) is app

    def test_picks_newest(self) -> None:
        old = IdaApp(path=Path("/app/IDA91.app"), version=(9, 1))
        new = IdaApp(path=Path("/app/IDA92.app"), version=(9, 2))
        # Caller sorts newest-first; choose_ida_app picks first.
        result = choose_ida_app([new, old])
        assert result is new

    def test_empty_list_raises(self) -> None:
        with pytest.raises(SystemExit):
            choose_ida_app([])
