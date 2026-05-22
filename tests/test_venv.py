"""Tests for _venv module: idalib helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ida_setup._venv import find_idapro_whl, resolve_framework_python


class TestFindIdaproWhl:
    def test_returns_none_when_no_whl(self, tmp_path: Path) -> None:
        assert find_idapro_whl(tmp_path) is None

    def test_returns_none_when_non_idapro_whl(self, tmp_path: Path) -> None:
        (tmp_path / "other-1.0-py3-none-any.whl").touch()
        assert find_idapro_whl(tmp_path) is None

    def test_returns_whl_when_present(self, tmp_path: Path) -> None:
        whl = tmp_path / "idapro-0.0.7-py3-none-any.whl"
        whl.touch()
        assert find_idapro_whl(tmp_path) == whl

    def test_returns_newest_when_multiple(self, tmp_path: Path) -> None:
        (tmp_path / "idapro-0.0.6-py3-none-any.whl").touch()
        newest = tmp_path / "idapro-0.0.7-py3-none-any.whl"
        newest.touch()
        assert find_idapro_whl(tmp_path) == newest


class TestResolveFrameworkPython:
    def test_returns_framework_python_from_venv_python_metadata(self, tmp_path: Path) -> None:
        framework = tmp_path / "pyenv" / "versions" / "3.12.12" / "Library" / "Frameworks" / "Python.framework"
        version_dir = framework / "Versions" / "3.12"
        framework_python = version_dir / "Python"
        framework_python.parent.mkdir(parents=True)
        framework_python.touch()

        result = MagicMock(returncode=0)
        result.stdout = json.dumps({"PYTHONFRAMEWORK": "Python", "sys.base_prefix": str(version_dir)})

        with patch("ida_setup._venv.run", return_value=result):
            assert resolve_framework_python(Path("/venv/bin/python3")) == framework_python

    def test_rejects_non_framework_python(self, tmp_path: Path) -> None:
        result = MagicMock(returncode=0)
        result.stdout = json.dumps({"PYTHONFRAMEWORK": "", "sys.base_prefix": str(tmp_path / "python")})

        with patch("ida_setup._venv.run", return_value=result):
            with pytest.raises(SystemExit, match="not a framework Python"):
                resolve_framework_python(Path("/venv/bin/python3"))

    def test_warns_but_accepts_non_pyenv_framework_python(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        framework = tmp_path / "other" / "Python.framework"
        version_dir = framework / "Versions" / "3.12"
        framework_python = version_dir / "Python"
        framework_python.parent.mkdir(parents=True)
        framework_python.touch()
        result = MagicMock(returncode=0)
        result.stdout = json.dumps({"PYTHONFRAMEWORK": "Python", "sys.base_prefix": str(version_dir)})

        with patch("ida_setup._venv.run", return_value=result):
            assert resolve_framework_python(Path("/venv/bin/python3")) == framework_python

        assert "not using the expected pyenv framework layout" in caplog.text
