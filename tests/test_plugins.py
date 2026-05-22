"""Tests for _plugins module: list, link, unlink, validation."""

from pathlib import Path
from unittest.mock import patch

import pytest

from ida_setup._common import cfg
from ida_setup._plugins import (
    _get_managed_targets,
    plugins_link,
    plugins_list,
    plugins_unlink,
    remove_existing_target,
    validate_entry_name,
)


@pytest.fixture(autouse=True)
def _reset_cfg() -> None:
    cfg.yes = True


class TestValidateEntryName:
    def test_simple_name(self) -> None:
        assert validate_entry_name("my_plugin.py") == "my_plugin.py"

    def test_directory_name(self) -> None:
        assert validate_entry_name("my_plugin") == "my_plugin"

    def test_empty_raises(self) -> None:
        with pytest.raises(SystemExit, match="must not be empty"):
            validate_entry_name("")

    def test_path_traversal_raises(self) -> None:
        with pytest.raises(SystemExit, match="invalid name"):
            validate_entry_name("../etc/passwd")

    def test_absolute_path_raises(self) -> None:
        with pytest.raises(SystemExit, match="invalid name"):
            validate_entry_name("/usr/bin/evil")

    def test_subpath_raises(self) -> None:
        with pytest.raises(SystemExit, match="invalid name"):
            validate_entry_name("subdir/plugin.py")


class TestRemoveExistingTarget:
    def test_removes_symlink(self, tmp_path: Path) -> None:
        target_file = tmp_path / "real.py"
        target_file.write_text("# plugin")
        link = tmp_path / "link.py"
        link.symlink_to(target_file)

        remove_existing_target(target=link, force=False)
        assert not link.exists()
        assert target_file.exists()

    def test_refuses_real_file_without_force(self, tmp_path: Path) -> None:
        real = tmp_path / "plugin.py"
        real.write_text("# real")
        with pytest.raises(SystemExit, match="--force"):
            remove_existing_target(target=real, force=False)

    def test_removes_real_file_with_force(self, tmp_path: Path) -> None:
        real = tmp_path / "plugin.py"
        real.write_text("# real")
        remove_existing_target(target=real, force=True)
        assert not real.exists()

    def test_removes_real_dir_with_force(self, tmp_path: Path) -> None:
        d = tmp_path / "plugin_dir"
        d.mkdir()
        (d / "file.py").write_text("# inner")
        remove_existing_target(target=d, force=True)
        assert not d.exists()


class TestPluginsList:
    def test_shows_both_dirs(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        plugins = tmp_path / "plugins"
        loaders = tmp_path / "loaders"
        plugins.mkdir()
        loaders.mkdir()
        (plugins / "myplugin.py").write_text("# plugin")
        (loaders / "myloader.py").write_text("# loader")

        with (
            patch("ida_setup._plugins.PLUGINS_DIR", plugins),
            patch("ida_setup._plugins.LOADERS_DIR", loaders),
        ):
            rc = plugins_list()

        assert rc == 0
        out = capsys.readouterr().out
        assert "plugins:" in out
        assert "myplugin.py" in out
        assert "loaders:" in out
        assert "myloader.py" in out

    def test_missing_dirs(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("ida_setup._plugins.PLUGINS_DIR", tmp_path / "no-plugins"),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "no-loaders"),
        ):
            rc = plugins_list()

        assert rc == 0
        out = capsys.readouterr().out
        assert out.count("(missing)") == 2

    def test_shows_symlink_target(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        real = tmp_path / "real.py"
        real.write_text("# plugin")
        (plugins / "sym.py").symlink_to(real)

        with (
            patch("ida_setup._plugins.PLUGINS_DIR", plugins),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
        ):
            rc = plugins_list()

        assert rc == 0
        assert "->" in capsys.readouterr().out

    def test_managed_symlink_tagged_with_dist(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        real = tmp_path / "real.py"
        real.write_text("# plugin")
        (plugins / "myplugin.py").symlink_to(real)

        managed = {str(real.resolve()): "my-package"}
        with (
            patch("ida_setup._plugins.PLUGINS_DIR", plugins),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
            patch("ida_setup._plugins._get_managed_targets", return_value={"plugins": managed, "loaders": {}}),
        ):
            rc = plugins_list()

        assert rc == 0
        out = capsys.readouterr().out
        assert "[my-package]" in out

    def test_manual_symlink_no_tag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        real = tmp_path / "real.py"
        real.write_text("# plugin")
        (plugins / "myplugin.py").symlink_to(real)

        with (
            patch("ida_setup._plugins.PLUGINS_DIR", plugins),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
            patch("ida_setup._plugins._get_managed_targets", return_value={"plugins": {}, "loaders": {}}),
        ):
            rc = plugins_list()

        assert rc == 0
        out = capsys.readouterr().out
        assert "[" not in out

    def test_broken_symlink_no_tag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        (plugins / "broken.py").symlink_to(tmp_path / "nonexistent.py")

        with (
            patch("ida_setup._plugins.PLUGINS_DIR", plugins),
            patch("ida_setup._plugins.LOADERS_DIR", tmp_path / "loaders"),
            patch("ida_setup._plugins._get_managed_targets", return_value={"plugins": {}, "loaders": {}}),
        ):
            rc = plugins_list()

        assert rc == 0
        out = capsys.readouterr().out
        assert "(broken)" in out
        assert "[" not in out


class TestGetManagedTargets:
    def test_no_venv(self) -> None:
        with patch("ida_setup._plugins.get_venv_python_exe", return_value=None):
            result = _get_managed_targets()
        assert result == {"plugins": {}, "loaders": {}}

    def test_discovery_failure(self, tmp_path: Path) -> None:
        fake_python = tmp_path / "python3"
        fake_python.touch()
        with (
            patch("ida_setup._plugins.get_venv_python_exe", return_value=fake_python),
            patch("ida_setup._plugins._discover_entrypoints", side_effect=RuntimeError("boom")),
        ):
            result = _get_managed_targets()
        assert result == {"plugins": {}, "loaders": {}}

    def test_returns_resolved_paths_with_dist(self, tmp_path: Path) -> None:
        fake_python = tmp_path / "python3"
        fake_python.touch()
        ep = {
            "plugins": {"foo": {"origin": str(tmp_path / "foo.py"), "dist": "foo-pkg"}},
            "loaders": {"bar": {"origin": str(tmp_path / "bar.py"), "dist": "bar-pkg"}},
        }
        with (
            patch("ida_setup._plugins.get_venv_python_exe", return_value=fake_python),
            patch("ida_setup._plugins._discover_entrypoints", return_value=ep),
        ):
            result = _get_managed_targets()
        foo_resolved = str(Path(tmp_path / "foo.py").resolve())
        bar_resolved = str(Path(tmp_path / "bar.py").resolve())
        assert result["plugins"][foo_resolved] == "foo-pkg"
        assert result["loaders"][bar_resolved] == "bar-pkg"


class TestPluginsLink:
    def test_no_sources_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="at least one --source"):
            plugins_link(sources=[], target_dir=tmp_path / "plugins", force=False)

    def test_source_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="does not exist"):
            plugins_link(sources=[tmp_path / "no-such.py"], target_dir=tmp_path / "plugins", force=False)

    def test_links_file(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        source = tmp_path / "my_plugin.py"
        source.write_text("# plugin")

        rc = plugins_link(sources=[source], target_dir=plugins, force=False)
        assert rc == 0
        link = plugins / "my_plugin.py"
        assert link.is_symlink()
        assert link.resolve() == source.resolve()

    def test_links_directory(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        source = tmp_path / "my_plugin"
        source.mkdir()
        (source / "__init__.py").write_text("")

        rc = plugins_link(sources=[source], target_dir=plugins, force=False)
        assert rc == 0
        assert (plugins / "my_plugin").is_symlink()

    def test_idempotent_same_target(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        source = tmp_path / "plugin.py"
        source.write_text("# plugin")
        (plugins / "plugin.py").symlink_to(source)

        rc = plugins_link(sources=[source], target_dir=plugins, force=False)
        assert rc == 0
        assert (plugins / "plugin.py").is_symlink()

    def test_links_to_loaders_dir(self, tmp_path: Path) -> None:
        loaders = tmp_path / "loaders"
        source = tmp_path / "my_loader.py"
        source.write_text("# loader")

        rc = plugins_link(sources=[source], target_dir=loaders, force=False)
        assert rc == 0
        assert (loaders / "my_loader.py").is_symlink()

    def test_force_overwrites_existing_symlink(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        old_source = tmp_path / "old.py"
        old_source.write_text("# old")
        new_source = tmp_path / "plugin.py"
        new_source.write_text("# new")
        (plugins / "plugin.py").symlink_to(old_source)

        rc = plugins_link(sources=[new_source], target_dir=plugins, force=True)
        assert rc == 0
        link = plugins / "plugin.py"
        assert link.is_symlink()
        assert link.resolve() == new_source.resolve()

    def test_force_overwrites_real_file(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        (plugins / "plugin.py").write_text("# real")
        source = tmp_path / "plugin.py"
        source.write_text("# new")

        rc = plugins_link(sources=[source], target_dir=plugins, force=True)
        assert rc == 0
        link = plugins / "plugin.py"
        assert link.is_symlink()
        assert link.resolve() == source.resolve()

    def test_refuses_overwrite_without_force(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        old_source = tmp_path / "old.py"
        old_source.write_text("# old")
        new_source = tmp_path / "plugin.py"
        new_source.write_text("# new")
        (plugins / "plugin.py").symlink_to(old_source)

        with pytest.raises(SystemExit, match="--force"):
            plugins_link(sources=[new_source], target_dir=plugins, force=False)


class TestPluginsUnlink:
    def test_no_names_raises(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        with pytest.raises(SystemExit, match="at least one --name"):
            plugins_unlink(names=[], target_dir=plugins, force=False)

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="does not exist"):
            plugins_unlink(names=["plugin.py"], target_dir=tmp_path / "no-such", force=False)

    def test_entry_not_found_raises(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        with pytest.raises(SystemExit, match="not found"):
            plugins_unlink(names=["no-such.py"], target_dir=plugins, force=False)

    def test_unlinks_symlink(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        source = tmp_path / "plugin.py"
        source.write_text("# plugin")
        link = plugins / "plugin.py"
        link.symlink_to(source)

        rc = plugins_unlink(names=["plugin.py"], target_dir=plugins, force=False)
        assert rc == 0
        assert not link.exists()
        assert source.exists()

    def test_refuses_real_file_without_force(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        (plugins / "real.py").write_text("# real")

        with pytest.raises(SystemExit, match="--force"):
            plugins_unlink(names=["real.py"], target_dir=plugins, force=False)

    def test_removes_real_file_with_force(self, tmp_path: Path) -> None:
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        (plugins / "real.py").write_text("# real")

        rc = plugins_unlink(names=["real.py"], target_dir=plugins, force=True)
        assert rc == 0
        assert not (plugins / "real.py").exists()
