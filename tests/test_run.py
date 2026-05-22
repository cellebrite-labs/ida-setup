"""Tests for _run module: clean_env_for_python_exec, require_core_tools, paths_equivalent."""

import shutil
from pathlib import Path

import pytest

from ida_setup._run import clean_env_for_python_exec, paths_equivalent, require_core_tools


class TestCleanEnv:
    def test_removes_venv_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VIRTUAL_ENV", "/some/venv")
        monkeypatch.setenv("PYTHONHOME", "/some/home")
        monkeypatch.setenv("PYTHONPATH", "/some/path")
        monkeypatch.setenv("PATH", "/usr/bin")

        env = clean_env_for_python_exec()

        assert "VIRTUAL_ENV" not in env
        assert "PYTHONHOME" not in env
        assert "PYTHONPATH" not in env
        assert env["PATH"] == "/usr/bin"

    def test_preserves_other_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_CUSTOM_VAR", "keepme")
        env = clean_env_for_python_exec()
        assert env["MY_CUSTOM_VAR"] == "keepme"

    def test_missing_vars_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        # Should not raise.
        env = clean_env_for_python_exec()
        assert "VIRTUAL_ENV" not in env

    def test_scrubs_venv_bin_from_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        venv = tmp_path / "myvenv"
        venv_bin = venv / "bin"
        venv_bin.mkdir(parents=True)
        monkeypatch.setenv("VIRTUAL_ENV", str(venv))
        monkeypatch.setenv("PATH", f"{venv_bin}:/usr/local/bin:/usr/bin")

        env = clean_env_for_python_exec()

        assert str(venv_bin) not in env["PATH"].split(":")
        assert "/usr/local/bin" in env["PATH"].split(":")
        assert "/usr/bin" in env["PATH"].split(":")

    def test_no_venv_leaves_path_intact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")

        env = clean_env_for_python_exec()

        assert env["PATH"] == "/usr/local/bin:/usr/bin"


class TestRequireCoreTools:
    def test_passes_when_all_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda t: f"/usr/bin/{t}")
        require_core_tools()  # should not raise

    def test_fails_when_tool_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_which(t: str) -> str | None:
            return None if t == "uv" else f"/usr/bin/{t}"

        monkeypatch.setattr(shutil, "which", fake_which)
        with pytest.raises(SystemExit, match="uv"):
            require_core_tools()


class TestPathsEquivalent:
    def test_same_path(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x")
        assert paths_equivalent(f, f) is True

    def test_symlink(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x")
        link = tmp_path / "b.txt"
        link.symlink_to(f)
        assert paths_equivalent(f, link) is True

    def test_different_files(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("x")
        b.write_text("y")
        assert paths_equivalent(a, b) is False

    def test_nonexistent_same_resolve(self) -> None:
        p = Path("/nonexistent/path/a")
        assert paths_equivalent(p, p) is True

    def test_nonexistent_different(self) -> None:
        a = Path("/nonexistent/a")
        b = Path("/nonexistent/b")
        assert paths_equivalent(a, b) is False
