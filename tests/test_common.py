"""Tests for _common module: config, venv helpers, pyvenv.cfg parsing."""

import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ida_setup._common import (
    cfg,
    confirm,
    get_venv_python_exe,
    read_pyvenv_cfg,
    require_macos,
    resolve_base_prefix,
)


class TestConfirm:
    def test_yes_flag_skips_prompt(self) -> None:
        cfg.yes = True
        confirm("do something?")

    def test_non_interactive_without_yes_raises(self) -> None:
        cfg.yes = False
        with patch.object(sys.stdin, "isatty", return_value=False):
            with pytest.raises(SystemExit, match="non-interactive"):
                confirm("do something?")

    def test_user_rejects_raises(self) -> None:
        cfg.yes = False
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="n"):
                with pytest.raises(SystemExit, match="aborted"):
                    confirm("do something?")

    def test_user_accepts(self) -> None:
        cfg.yes = False
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="y"):
                confirm("do something?")


class TestRequireMacos:
    def test_darwin_passes(self) -> None:
        with patch.object(sys, "platform", "darwin"):
            require_macos()

    def test_linux_fails(self) -> None:
        with patch.object(sys, "platform", "linux"):
            with pytest.raises(SystemExit, match="macOS only"):
                require_macos()


class TestGetVenvPythonExe:
    def test_returns_none_when_dir_missing(self, tmp_path: Path) -> None:
        with patch("ida_setup._common.VENV_DIR", tmp_path / "no-such"):
            assert get_venv_python_exe() is None

    def test_returns_none_when_exe_missing(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "bin").mkdir()
        with patch("ida_setup._common.VENV_DIR", venv_dir):
            assert get_venv_python_exe() is None

    def test_returns_exe_when_present(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / "venv"
        (venv_dir / "bin").mkdir(parents=True)
        exe = venv_dir / "bin" / "python3"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        with patch("ida_setup._common.VENV_DIR", venv_dir):
            result = get_venv_python_exe()
            assert result is not None
            assert result == exe


class TestReadPyvenvCfg:
    def test_missing_venv(self, tmp_path: Path) -> None:
        assert read_pyvenv_cfg(tmp_path) is None

    def test_reads_all_keys(self, tmp_path: Path) -> None:
        (tmp_path / "pyvenv.cfg").write_text(
            "home = /opt/homebrew/opt/python@3.12/bin\n"
            "version = 3.12.12\n",
        )  # fmt: skip
        result = read_pyvenv_cfg(tmp_path)
        assert result is not None
        assert result["home"] == "/opt/homebrew/opt/python@3.12/bin"
        assert result["version"] == "3.12.12"

    def test_no_home_key(self, tmp_path: Path) -> None:
        (tmp_path / "pyvenv.cfg").write_text("version = 3.12.12\n")
        result = read_pyvenv_cfg(tmp_path)
        assert result is not None
        assert "home" not in result


class TestResolveBasePrefix:
    def test_missing_venv(self, tmp_path: Path) -> None:
        assert resolve_base_prefix(tmp_path) is None

    def test_no_home_key(self, tmp_path: Path) -> None:
        (tmp_path / "pyvenv.cfg").write_text("version = 3.12.12\n")
        assert resolve_base_prefix(tmp_path) is None

    def test_home_dir_exists(self, tmp_path: Path) -> None:
        base = tmp_path / "python3.12"
        bin_dir = base / "bin"
        bin_dir.mkdir(parents=True)
        (tmp_path / "pyvenv.cfg").write_text(f"home = {bin_dir}\n")
        assert resolve_base_prefix(tmp_path) == base

    def test_resolves_symlinks(self, tmp_path: Path) -> None:
        cellar = tmp_path / "Cellar" / "python@3.12" / "3.12.12_2"
        cellar_bin = cellar / "bin"
        cellar_bin.mkdir(parents=True)

        opt = tmp_path / "opt" / "python@3.12"
        opt.parent.mkdir(parents=True)
        opt.symlink_to(cellar)

        (tmp_path / "pyvenv.cfg").write_text(f"home = {opt / 'bin'}\n")
        result = resolve_base_prefix(tmp_path)
        assert result == cellar

    def test_home_does_not_exist(self, tmp_path: Path) -> None:
        (tmp_path / "pyvenv.cfg").write_text("home = /nonexistent/python/bin\n")
        result = resolve_base_prefix(tmp_path)
        assert result == Path("/nonexistent/python")
