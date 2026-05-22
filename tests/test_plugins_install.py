"""Tests for plugins install (entry-point based install + symlink)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ida_setup._plugins import _discover_entrypoints, _link_entrypoints, plugins_install, plugins_relink


class TestLinkEntrypoints:
    def test_creates_symlinks_with_suffix(self, tmp_path: Path) -> None:
        origin = tmp_path / "src" / "keypatch.py"
        origin.parent.mkdir()
        origin.write_text("# plugin")

        target_dir = tmp_path / "plugins"
        linked = _link_entrypoints({"keypatch": {"origin": str(origin), "dist": "keypatch"}}, target_dir, "_plugin")

        assert len(linked) == 1
        link = target_dir / "keypatch_plugin.py"
        assert link.is_symlink()
        assert link.resolve() == origin.resolve()

    def test_overwrites_existing_symlink(self, tmp_path: Path) -> None:
        old_origin = tmp_path / "old.py"
        old_origin.write_text("# old")
        new_origin = tmp_path / "new.py"
        new_origin.write_text("# new")

        target_dir = tmp_path / "plugins"
        target_dir.mkdir()
        link = target_dir / "myplugin_plugin.py"
        link.symlink_to(old_origin)

        _link_entrypoints({"myplugin": {"origin": str(new_origin), "dist": "myplugin"}}, target_dir, "_plugin")
        assert link.resolve() == new_origin.resolve()

    def test_refuses_to_overwrite_real_file(self, tmp_path: Path) -> None:
        origin = tmp_path / "new.py"
        origin.write_text("# new")

        target_dir = tmp_path / "plugins"
        target_dir.mkdir()
        real_file = target_dir / "myplugin_plugin.py"
        real_file.write_text("# keep")

        with pytest.raises(SystemExit, match="refusing to overwrite real file/directory"):
            _link_entrypoints({"myplugin": {"origin": str(origin), "dist": "myplugin"}}, target_dir, "_plugin")

        assert real_file.read_text() == "# keep"

    def test_creates_target_dir(self, tmp_path: Path) -> None:
        origin = tmp_path / "mod.py"
        origin.write_text("# loader")

        target_dir = tmp_path / "nested" / "loaders"
        _link_entrypoints({"myloader": {"origin": str(origin), "dist": "myloader"}}, target_dir, "_loader")
        assert (target_dir / "myloader_loader.py").is_symlink()


class TestDiscoverEntrypoints:
    def test_parses_json_from_subprocess(self, tmp_path: Path) -> None:
        expected = {"plugins": {"foo": {"origin": "/path/to/foo.py", "dist": "foo-pkg"}}, "loaders": {}}
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(expected)

        with patch("ida_setup._plugins.run", return_value=mock_result) as mock_run:
            result = _discover_entrypoints(Path("/usr/bin/python3"))

        assert result == expected
        call_args = mock_run.call_args
        assert call_args[0][0][0] == "/usr/bin/python3"
        assert call_args[0][0][1] == "-c"
        assert call_args[1]["check"] is True
        assert call_args[1]["capture"] is True


class TestPluginsInstall:
    def test_installs_and_links_plugins(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        origin = tmp_path / "src" / "myplugin.py"
        origin.parent.mkdir()
        origin.write_text("# plugin")

        before_data = {"plugins": {}, "loaders": {}}
        after_data = {"plugins": {"myplugin": {"origin": str(origin), "dist": "some-package"}}, "loaders": {}}

        call_count = 0

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                r = MagicMock()
                r.stdout = json.dumps(before_data)
                return r
            if call_count == 2:
                assert cmd[0] == "uv"
                return MagicMock(returncode=0)
            r = MagicMock()
            r.stdout = json.dumps(after_data)
            return r

        plugins_dir = tmp_path / "plugins"
        loaders_dir = tmp_path / "loaders"

        with (
            patch("ida_setup._plugins.run", side_effect=fake_run),
            patch("ida_setup._plugins.PLUGINS_DIR", plugins_dir),
            patch("ida_setup._plugins.LOADERS_DIR", loaders_dir),
        ):
            rc = plugins_install(pip_args=["some-package"], python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        assert (plugins_dir / "myplugin_plugin.py").is_symlink()
        out = capsys.readouterr().out
        assert "plugin:" in out
        assert "ok: installed" in out

    def test_installs_and_links_loaders(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        origin = tmp_path / "src" / "myloader.py"
        origin.parent.mkdir()
        origin.write_text("# loader")

        before_data = {"plugins": {}, "loaders": {}}
        after_data = {"plugins": {}, "loaders": {"myloader": {"origin": str(origin), "dist": "loader-pkg"}}}

        call_count = 0

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                r = MagicMock()
                r.stdout = json.dumps(before_data)
                return r
            if call_count == 2:
                return MagicMock(returncode=0)
            r = MagicMock()
            r.stdout = json.dumps(after_data)
            return r

        plugins_dir = tmp_path / "plugins"
        loaders_dir = tmp_path / "loaders"

        with (
            patch("ida_setup._plugins.run", side_effect=fake_run),
            patch("ida_setup._plugins.PLUGINS_DIR", plugins_dir),
            patch("ida_setup._plugins.LOADERS_DIR", loaders_dir),
        ):
            rc = plugins_install(pip_args=["loader-pkg"], python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        assert (loaders_dir / "myloader_loader.py").is_symlink()
        out = capsys.readouterr().out
        assert "loader:" in out

    def test_no_entrypoints_found(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        ep_data = {"plugins": {}, "loaders": {}}

        call_count = 0

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return MagicMock(returncode=0)
            r = MagicMock()
            r.stdout = json.dumps(ep_data)
            return r

        with (
            patch("ida_setup._plugins.run", side_effect=fake_run),
            patch("ida_setup._plugins.PLUGINS_DIR", tmp_path / "plugins"),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
        ):
            rc = plugins_install(pip_args=["no-ep-pkg"], python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        assert "no new ida_plugins or ida_loaders entry points found" in capsys.readouterr().out

    def test_skips_preexisting_plugins(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Plugins that existed before install are not re-linked."""
        origin = tmp_path / "src" / "existing.py"
        origin.parent.mkdir()
        origin.write_text("# existing")

        ep_data = {"plugins": {"existing": {"origin": str(origin), "dist": "existing-pkg"}}, "loaders": {}}

        call_count = 0

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return MagicMock(returncode=0)
            r = MagicMock()
            r.stdout = json.dumps(ep_data)
            return r

        plugins_dir = tmp_path / "plugins"

        with (
            patch("ida_setup._plugins.run", side_effect=fake_run),
            patch("ida_setup._plugins.PLUGINS_DIR", plugins_dir),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
        ):
            rc = plugins_install(pip_args=["other-pkg"], python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        assert not (plugins_dir / "existing_plugin.py").exists()
        assert "no new ida_plugins or ida_loaders entry points found" in capsys.readouterr().out

    def test_pip_args_passed_through(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Extra pip args like -e are forwarded to uv pip install."""
        ep_data = {"plugins": {}, "loaders": {}}
        captured_cmds: list[list[str]] = []

        call_count = 0

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            captured_cmds.append(cmd)
            if call_count == 2:
                return MagicMock(returncode=0)
            r = MagicMock()
            r.stdout = json.dumps(ep_data)
            return r

        with (
            patch("ida_setup._plugins.run", side_effect=fake_run),
            patch("ida_setup._plugins.PLUGINS_DIR", tmp_path / "plugins"),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
        ):
            plugins_install(pip_args=["-e", "/path/to/pkg"], python_exe=Path("/usr/bin/python3"))

        install_cmd = captured_cmds[1]
        assert install_cmd[:3] == ["uv", "pip", "install"]
        assert "-e" in install_cmd
        assert "/path/to/pkg" in install_cmd

    def test_mixed_plugins_and_loaders(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A package that registers both plugins and loaders."""
        plugin_origin = tmp_path / "src" / "myplugin.py"
        loader_origin = tmp_path / "src" / "myloader.py"
        plugin_origin.parent.mkdir()
        plugin_origin.write_text("# plugin")
        loader_origin.write_text("# loader")

        before_data = {"plugins": {}, "loaders": {}}
        after_data = {
            "plugins": {"myplugin": {"origin": str(plugin_origin), "dist": "combo-pkg"}},
            "loaders": {"myloader": {"origin": str(loader_origin), "dist": "combo-pkg"}},
        }

        call_count = 0

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                r = MagicMock()
                r.stdout = json.dumps(before_data)
                return r
            if call_count == 2:
                return MagicMock(returncode=0)
            r = MagicMock()
            r.stdout = json.dumps(after_data)
            return r

        plugins_dir = tmp_path / "plugins"
        loaders_dir = tmp_path / "loaders"

        with (
            patch("ida_setup._plugins.run", side_effect=fake_run),
            patch("ida_setup._plugins.PLUGINS_DIR", plugins_dir),
            patch("ida_setup._plugins.LOADERS_DIR", loaders_dir),
        ):
            rc = plugins_install(pip_args=["combo-pkg"], python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        assert (plugins_dir / "myplugin_plugin.py").is_symlink()
        assert (loaders_dir / "myloader_loader.py").is_symlink()
        out = capsys.readouterr().out
        assert "plugin:" in out
        assert "loader:" in out
        assert "ok: installed" in out

    def test_origin_change_relinks(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """An update that changes a plugin's origin path triggers a relink."""
        old_origin = tmp_path / "src" / "v1" / "myplugin.py"
        new_origin = tmp_path / "src" / "v2" / "myplugin.py"
        old_origin.parent.mkdir(parents=True)
        new_origin.parent.mkdir(parents=True)
        old_origin.write_text("# v1")
        new_origin.write_text("# v2")

        before_data = {"plugins": {"myplugin": {"origin": str(old_origin), "dist": "myplugin"}}, "loaders": {}}
        after_data = {"plugins": {"myplugin": {"origin": str(new_origin), "dist": "myplugin"}}, "loaders": {}}

        call_count = 0

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                r = MagicMock()
                r.stdout = json.dumps(before_data)
                return r
            if call_count == 2:
                return MagicMock(returncode=0)
            r = MagicMock()
            r.stdout = json.dumps(after_data)
            return r

        plugins_dir = tmp_path / "plugins"

        with (
            patch("ida_setup._plugins.run", side_effect=fake_run),
            patch("ida_setup._plugins.PLUGINS_DIR", plugins_dir),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
        ):
            rc = plugins_install(pip_args=["myplugin"], python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        link = plugins_dir / "myplugin_plugin.py"
        assert link.is_symlink()
        assert link.resolve() == new_origin.resolve()
        assert "ok: installed" in capsys.readouterr().out

    def test_relink_recreates_all(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        origin = tmp_path / "src" / "existing.py"
        origin.parent.mkdir()
        origin.write_text("# existing")

        ep_data = {"plugins": {"existing": {"origin": str(origin), "dist": "existing-pkg"}}, "loaders": {}}
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(ep_data)

        plugins_dir = tmp_path / "plugins"

        with (
            patch("ida_setup._plugins.run", return_value=mock_result),
            patch("ida_setup._plugins.PLUGINS_DIR", plugins_dir),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
        ):
            rc = plugins_relink(python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        assert (plugins_dir / "existing_plugin.py").is_symlink()
        assert "ok: relinked" in capsys.readouterr().out

    def test_relink_no_entrypoints(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        ep_data = {"plugins": {}, "loaders": {}}
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(ep_data)

        with (
            patch("ida_setup._plugins.run", return_value=mock_result),
            patch("ida_setup._plugins.PLUGINS_DIR", tmp_path / "plugins"),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
        ):
            rc = plugins_relink(python_exe=Path("/usr/bin/python3"))

        assert rc == 0
        assert "no ida_plugins or ida_loaders entry points found" in capsys.readouterr().out
