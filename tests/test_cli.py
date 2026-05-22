"""Tests for cli module: argument parsing, _resolve_default_python, command dispatch."""

import argparse
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ida_setup.cli import (
    _dylib_matches_prefix,
    _resolve_default_python,
    _resolve_target_dir,
    cmd_status,
    cmd_venv,
    main,
)

# -- Helpers -----------------------------------------------------------------


def _make_exe(path: Path) -> Path:
    """Create a fake executable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _make_args(
    *,
    python: str | None = None,
    ida: str | None = None,
    verbose: bool = False,
    yes: bool = False,
) -> argparse.Namespace:
    """Build a minimal Namespace matching what main() produces."""
    ns = argparse.Namespace()
    ns.python = python
    ns.ida = ida
    ns.verbose = verbose
    ns._cfg = None  # unused, cfg is global now
    return ns


# -- _resolve_default_python -------------------------------------------------


class TestResolveDefaultPython:
    def test_explicit_path(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path / "bin" / "python3")
        args = _make_args(python=str(exe))
        result = _resolve_default_python(args)
        assert result == exe

    def test_explicit_path_not_found(self, tmp_path: Path) -> None:
        args = _make_args(python=str(tmp_path / "no-such-python"))
        with pytest.raises(SystemExit, match="not found or not executable"):
            _resolve_default_python(args)

    def test_launchctl_fallback(self, tmp_path: Path) -> None:
        exe = _make_exe(tmp_path / "venv" / "bin" / "python3")
        args = _make_args()
        with patch("ida_setup.cli.get_ida_venv_var", return_value=str(exe)):
            result = _resolve_default_python(args)
        assert result == exe

    def test_env_var_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = _make_exe(tmp_path / "venv" / "bin" / "python3")
        args = _make_args()
        with patch("ida_setup.cli.get_ida_venv_var", return_value=""):
            monkeypatch.setenv("IDAPYTHON_VENV_EXECUTABLE", str(exe))
            result = _resolve_default_python(args)
        assert result == exe

    def test_launchctl_preferred_over_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        lc_exe = _make_exe(tmp_path / "lc" / "bin" / "python3")
        env_exe = _make_exe(tmp_path / "env" / "bin" / "python3")
        args = _make_args()
        with patch("ida_setup.cli.get_ida_venv_var", return_value=str(lc_exe)):
            monkeypatch.setenv("IDAPYTHON_VENV_EXECUTABLE", str(env_exe))
            result = _resolve_default_python(args)
        assert result == lc_exe

    def test_no_python_no_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        args = _make_args()
        with patch("ida_setup.cli.get_ida_venv_var", return_value=""):
            monkeypatch.delenv("IDAPYTHON_VENV_EXECUTABLE", raising=False)
            with pytest.raises(SystemExit, match="no Python interpreter specified"):
                _resolve_default_python(args)

    def test_launchctl_returns_nonexistent_falls_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        args = _make_args()
        with patch("ida_setup.cli.get_ida_venv_var", return_value=str(tmp_path / "gone")):
            monkeypatch.delenv("IDAPYTHON_VENV_EXECUTABLE", raising=False)
            with pytest.raises(SystemExit, match="no Python interpreter specified"):
                _resolve_default_python(args)

    def test_env_var_nonexistent_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        args = _make_args()
        with patch("ida_setup.cli.get_ida_venv_var", return_value=""):
            monkeypatch.setenv("IDAPYTHON_VENV_EXECUTABLE", str(tmp_path / "gone"))
            with pytest.raises(SystemExit, match="no Python interpreter specified"):
                _resolve_default_python(args)


# -- Argument parsing --------------------------------------------------------


class TestArgParsing:
    """Test that main() parses commands correctly.

    These mock require_macos and require_core_tools since we're testing
    parsing, not the actual commands.
    """

    _patches = (
        "ida_setup.cli.require_macos",
        "ida_setup.cli.require_core_tools",
    )

    def _run(self, argv: list[str], extra_patches: dict | None = None) -> int:
        patches = {p: lambda *a, **k: None for p in self._patches}
        if extra_patches:
            patches.update(extra_patches)
        ctx = [patch(k, v) for k, v in patches.items()]
        for c in ctx:
            c.__enter__()
        try:
            return main(argv)
        finally:
            for c in reversed(ctx):
                c.__exit__(None, None, None)

    def test_no_command_exits(self) -> None:
        with pytest.raises(SystemExit):
            self._run([])

    def test_unknown_command_exits(self) -> None:
        with pytest.raises(SystemExit):
            self._run(["bogus"])

    def test_status_probe_dispatches(self) -> None:
        called = {}

        def fake_status(args: argparse.Namespace) -> int:
            called["probe"] = args.probe
            return 0

        with patch("ida_setup.cli.cmd_status", fake_status):
            rc = self._run(["status", "--probe"])
        assert rc == 0
        assert called["probe"] is True

    def test_status_import_without_probe_fails(self) -> None:
        with pytest.raises(SystemExit, match="--import requires --probe"):
            self._run(["status", "--import", "pydantic"])

    def test_status_dispatches(self) -> None:
        called = {}

        def fake_status(args: argparse.Namespace) -> int:
            called["yes"] = True
            return 0

        with patch("ida_setup.cli.cmd_status", fake_status):
            rc = self._run(["status"])
        assert rc == 0
        assert called.get("yes")

    def test_venv_dispatches(self) -> None:
        called = {}

        def fake_venv(args: argparse.Namespace) -> int:
            called["yes"] = True
            return 0

        with patch("ida_setup.cli.cmd_venv", fake_venv):
            rc = self._run(["venv"])
        assert rc == 0
        assert called.get("yes")

    def test_plugin_requires_subcommand(self) -> None:
        with pytest.raises(SystemExit):
            self._run(["plugin"])

    def test_plugin_list_dispatches(self) -> None:
        called = {}

        def fake_list(args: argparse.Namespace) -> int:
            called["yes"] = True
            return 0

        with patch("ida_setup.cli.cmd_plugins_list", fake_list):
            rc = self._run(["plugin", "list"])
        assert rc == 0
        assert called.get("yes")

    def test_plugin_link_dispatches(self) -> None:
        called = {}

        def fake_link(args: argparse.Namespace) -> int:
            called["source"] = args.source
            called["loader"] = args.loader
            return 0

        with patch("ida_setup.cli.cmd_plugins_link", fake_link):
            rc = self._run(["plugin", "link", "/path/to/plugin.py"])
        assert rc == 0
        assert called["source"] == ["/path/to/plugin.py"]
        assert called["loader"] is False

    def test_plugin_link_loader_flag(self) -> None:
        called = {}

        def fake_link(args: argparse.Namespace) -> int:
            called["loader"] = args.loader
            return 0

        with patch("ida_setup.cli.cmd_plugins_link", fake_link):
            rc = self._run(["plugin", "link", "/path/to/x.py", "--loader"])
        assert rc == 0
        assert called["loader"] is True

    def test_plugin_unlink_dispatches(self) -> None:
        called = {}

        def fake_unlink(args: argparse.Namespace) -> int:
            called["name"] = args.name
            called["loader"] = args.loader
            return 0

        with patch("ida_setup.cli.cmd_plugins_unlink", fake_unlink):
            rc = self._run(["plugin", "unlink", "myplugin.py"])
        assert rc == 0
        assert called["name"] == ["myplugin.py"]
        assert called["loader"] is False

    def test_plugin_unlink_loader_flag(self) -> None:
        called = {}

        def fake_unlink(args: argparse.Namespace) -> int:
            called["loader"] = args.loader
            return 0

        with patch("ida_setup.cli.cmd_plugins_unlink", fake_unlink):
            rc = self._run(["plugin", "unlink", "x.py", "--loader"])
        assert rc == 0
        assert called["loader"] is True

    def test_plugin_install_dispatches(self) -> None:
        captured = {}

        def fake_install(args: argparse.Namespace) -> int:
            captured["passthrough"] = list(args._passthrough)
            return 0

        with patch("ida_setup.cli.cmd_plugins_install", fake_install):
            rc = self._run(["plugin", "install", "keypatch"])
        assert rc == 0
        assert captured["passthrough"] == ["keypatch"]

    def test_plugin_install_passthrough(self) -> None:
        captured = {}

        def fake_install(args: argparse.Namespace) -> int:
            captured["passthrough"] = list(args._passthrough)
            return 0

        with patch("ida_setup.cli.cmd_plugins_install", fake_install):
            rc = self._run(["plugin", "install", "-e", "/path/to/pkg"])
        assert rc == 0
        assert captured["passthrough"] == ["-e", "/path/to/pkg"]

    def test_plugin_install_forwards_common_options_after_install(self) -> None:
        captured = {}

        def fake_install(args: argparse.Namespace) -> int:
            captured["verbose"] = args.verbose
            captured["passthrough"] = list(args._passthrough)
            return 0

        with patch("ida_setup.cli.cmd_plugins_install", fake_install):
            rc = self._run(["plugin", "install", "--verbose", "keypatch"])
        assert rc == 0
        assert captured["verbose"] is False
        assert captured["passthrough"] == ["--verbose", "keypatch"]

    def test_plugin_relink_dispatches(self) -> None:
        captured = {}

        def fake_relink(args: argparse.Namespace) -> int:
            captured["called"] = True
            return 0

        with patch("ida_setup.cli.cmd_plugins_relink", fake_relink):
            rc = self._run(["plugin", "relink"])
        assert rc == 0
        assert captured["called"]

    def test_pip_passthrough(self) -> None:
        captured = {}

        def fake_pip(args: argparse.Namespace) -> int:
            captured["passthrough"] = list(args._passthrough)
            return 0

        with patch("ida_setup.cli.cmd_pip", fake_pip):
            rc = self._run(["pip", "install", "pydantic"])
        assert rc == 0
        assert captured["passthrough"] == ["install", "pydantic"]

    def test_pip_forwards_common_options_after_command(self) -> None:
        captured = {}

        def fake_pip(args: argparse.Namespace) -> int:
            captured["verbose"] = args.verbose
            captured["passthrough"] = list(args._passthrough)
            return 0

        with patch("ida_setup.cli.cmd_pip", fake_pip):
            rc = self._run(["pip", "--verbose", "install", "pydantic"])
        assert rc == 0
        assert captured["verbose"] is False
        assert captured["passthrough"] == ["--verbose", "install", "pydantic"]

    def test_python_passthrough(self) -> None:
        captured = {}

        def fake_python(args: argparse.Namespace) -> int:
            captured["passthrough"] = list(args._passthrough)
            return 0

        with patch("ida_setup.cli.cmd_python", fake_python):
            rc = self._run(["python", "-c", "print('hi')"])
        assert rc == 0
        assert captured["passthrough"] == ["-c", "print('hi')"]

    def test_yes_flag_propagates(self) -> None:
        captured = {}

        def fake_status(args: argparse.Namespace) -> int:
            from ida_setup._common import cfg

            captured["yes"] = cfg.yes
            return 0

        with patch("ida_setup.cli.cmd_status", fake_status):
            self._run(["--yes", "status"])
        assert captured["yes"] is True

    def test_verbose_flag_propagates(self) -> None:
        captured = {}

        def fake_status(args: argparse.Namespace) -> int:
            captured["verbose"] = args.verbose
            return 0

        with patch("ida_setup.cli.cmd_status", fake_status):
            self._run(["--verbose", "status"])
        assert captured["verbose"] is True

    def test_unrecognized_args_rejected_for_non_passthrough(self) -> None:
        def fake_status(args: argparse.Namespace) -> int:
            return 0

        with patch("ida_setup.cli.cmd_status", fake_status):
            with pytest.raises(SystemExit):
                self._run(["status", "--bogus"])


# -- cmd_status handler tests ------------------------------------------------


class TestCmdStatusProbe:
    def test_probe_calls_run_probe(self, tmp_path: Path) -> None:
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        args = _make_args()
        args.probe = True
        args.import_name = []

        with (
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.run_probe", return_value=0) as mock_probe,
        ):
            rc = cmd_status(args)

        assert rc == 0
        mock_probe.assert_called_once()

    def test_probe_passes_import_names(self, tmp_path: Path) -> None:
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        args = _make_args()
        args.probe = True
        args.import_name = ["pydantic", "requests"]

        with (
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.run_probe", return_value=0) as mock_probe,
        ):
            cmd_status(args)

        call_kwargs = mock_probe.call_args[1]
        assert call_kwargs["import_names"] == ["pydantic", "requests"]

    def test_import_without_probe_fails(self) -> None:
        args = _make_args()
        args.probe = False
        args.import_name = ["pydantic"]

        with pytest.raises(SystemExit, match="--import requires --probe"):
            cmd_status(args)


# -- cmd_venv handler tests --------------------------------------------------


class TestCmdVenv:
    def test_existing_venv_upgrades_idapro(self, tmp_path: Path) -> None:
        from ida_setup._common import cfg
        from ida_setup._ida import IdaApp

        cfg.yes = True

        venv_python = _make_exe(tmp_path / "venv" / "bin" / "python3")
        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))

        with (
            patch("ida_setup.cli.get_venv_python_exe", return_value=venv_python),
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.resolve_framework_python", return_value=Path("/python/Python")),
            patch("ida_setup.cli.switch_idapython"),
            patch("ida_setup.cli.install_idapro_package") as mock_install,
            patch("ida_setup.cli.run_py_activate_idalib"),
            patch("ida_setup.cli.verify_idalib_import"),
            patch("ida_setup.cli.install_launch_agent"),
        ):
            args = _make_args()
            rc = cmd_venv(args)

        assert rc == 0
        mock_install.assert_called_once_with(app=app, venv_python=venv_python)

    def test_no_python_raises(self) -> None:
        with patch("ida_setup.cli.get_venv_python_exe", return_value=None):
            args = _make_args(python=None)
            with pytest.raises(SystemExit, match="base Python interpreter is required"):
                cmd_venv(args)

    def test_python_ida_rejected(self) -> None:
        with patch("ida_setup.cli.get_venv_python_exe", return_value=None):
            args = _make_args(python="ida")
            with pytest.raises(SystemExit, match="--python ida cannot be used"):
                cmd_venv(args)

    def test_creates_venv_and_installs(self, tmp_path: Path) -> None:
        from ida_setup._common import cfg
        from ida_setup._ida import IdaApp

        cfg.yes = True

        base_python = _make_exe(tmp_path / "base" / "python3")
        venv_python = _make_exe(tmp_path / "venv" / "bin" / "python3")
        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))

        call_count = 0

        def fake_get_venv_python(*a: object, **kw: object) -> Path | None:
            nonlocal call_count
            call_count += 1
            # First call: venv doesn't exist. Second call: it does.
            return None if call_count == 1 else venv_python

        with (
            patch("ida_setup.cli.get_venv_python_exe", side_effect=fake_get_venv_python),
            patch("ida_setup.cli.resolve_python_for_cli", return_value=base_python),
            patch("ida_setup.cli.VENV_DIR", tmp_path / "venv"),
            patch("ida_setup.cli.run") as mock_run,
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.resolve_framework_python", return_value=Path("/python/Python")),
            patch("ida_setup.cli.switch_idapython"),
            patch("ida_setup.cli.install_idapro_package"),
            patch("ida_setup.cli.run_py_activate_idalib"),
            patch("ida_setup.cli.verify_idalib_import"),
            patch("ida_setup.cli.install_launch_agent"),
        ):
            args = _make_args(python=str(base_python))
            rc = cmd_venv(args)

        assert rc == 0
        # Verify uv venv was called.
        uv_call = mock_run.call_args_list[0]
        assert uv_call[0][0][0] == "uv"
        assert uv_call[0][0][1] == "venv"

    def test_invalid_base_python_does_not_create_venv(self, tmp_path: Path) -> None:
        base_python = _make_exe(tmp_path / "base" / "python3")

        with (
            patch("ida_setup.cli.get_venv_python_exe", return_value=None),
            patch("ida_setup.cli.resolve_python_for_cli", return_value=base_python),
            patch("ida_setup.cli.resolve_framework_python", side_effect=SystemExit("not a framework Python")),
            patch("ida_setup.cli.run") as mock_run,
        ):
            args = _make_args(python=str(base_python))
            with pytest.raises(SystemExit, match="not a framework Python"):
                cmd_venv(args)

        mock_run.assert_not_called()

    def test_venv_not_found_after_creation_raises(self, tmp_path: Path) -> None:
        from ida_setup._common import cfg

        cfg.yes = True

        base_python = _make_exe(tmp_path / "base" / "python3")

        with (
            patch("ida_setup.cli.get_venv_python_exe", return_value=None),
            patch("ida_setup.cli.resolve_python_for_cli", return_value=base_python),
            patch("ida_setup.cli.resolve_framework_python", return_value=Path("/python/Python")),
            patch("ida_setup.cli.VENV_DIR", tmp_path / "venv"),
            patch("ida_setup.cli.run"),
        ):
            args = _make_args(python=str(base_python))
            with pytest.raises(SystemExit, match="venv python not found after creation"):
                cmd_venv(args)


# -- _offer_launchagent tests ------------------------------------------------


class TestOfferLaunchagent:
    def test_yes_flag_auto_installs(self, tmp_path: Path) -> None:
        from ida_setup._common import cfg
        from ida_setup.cli import _offer_launchagent

        cfg.yes = True

        venv_python = _make_exe(tmp_path / "venv" / "bin" / "python3")

        with patch("ida_setup.cli.install_launch_agent") as mock_la:
            _offer_launchagent(venv_python=venv_python)

        mock_la.assert_called_once_with(venv_python_exe=venv_python)

    def test_non_interactive_prints_tip(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from ida_setup._common import cfg
        from ida_setup.cli import _offer_launchagent

        cfg.yes = False

        venv_python = _make_exe(tmp_path / "venv" / "bin" / "python3")

        with (
            patch("sys.stdin") as mock_stdin,
            patch("ida_setup.cli.install_launch_agent") as mock_la,
        ):
            mock_stdin.isatty.return_value = False
            _offer_launchagent(venv_python=venv_python)

        mock_la.assert_not_called()
        assert "tip:" in capsys.readouterr().out

    def test_user_accepts(self, tmp_path: Path) -> None:
        from ida_setup._common import cfg
        from ida_setup.cli import _offer_launchagent

        cfg.yes = False

        venv_python = _make_exe(tmp_path / "venv" / "bin" / "python3")

        with (
            patch("sys.stdin") as mock_stdin,
            patch("builtins.input", return_value="y"),
            patch("ida_setup.cli.install_launch_agent") as mock_la,
        ):
            mock_stdin.isatty.return_value = True
            _offer_launchagent(venv_python=venv_python)

        mock_la.assert_called_once()

    def test_user_declines(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from ida_setup._common import cfg
        from ida_setup.cli import _offer_launchagent

        cfg.yes = False

        venv_python = _make_exe(tmp_path / "venv" / "bin" / "python3")

        with (
            patch("sys.stdin") as mock_stdin,
            patch("builtins.input", return_value="n"),
            patch("ida_setup.cli.install_launch_agent") as mock_la,
        ):
            mock_stdin.isatty.return_value = True
            _offer_launchagent(venv_python=venv_python)

        mock_la.assert_not_called()
        assert "skipped" in capsys.readouterr().out


# -- _dylib_matches_prefix tests ---------------------------------------------


class TestDylibMatchesPrefix:
    def test_matching_path(self, tmp_path: Path) -> None:
        prefix = tmp_path / "python3.12"
        dylib = prefix / "lib" / "libpython3.12.dylib"
        dylib.parent.mkdir(parents=True)
        dylib.touch()
        assert _dylib_matches_prefix(str(dylib), prefix) is True

    def test_non_matching_path(self, tmp_path: Path) -> None:
        prefix = tmp_path / "python3.12"
        prefix.mkdir()
        dylib = tmp_path / "other" / "libpython3.12.dylib"
        dylib.parent.mkdir(parents=True)
        dylib.touch()
        assert _dylib_matches_prefix(str(dylib), prefix) is False

    def test_nonexistent_dylib_under_prefix(self) -> None:
        # Non-existent path can't be resolved, uses raw path
        assert _dylib_matches_prefix("/opt/python/lib/libpython.dylib", Path("/opt/python")) is True

    def test_nonexistent_dylib_not_under_prefix(self) -> None:
        assert _dylib_matches_prefix("/other/lib/libpython.dylib", Path("/opt/python")) is False


# -- _resolve_target_dir tests -----------------------------------------------


class TestResolveTargetDir:
    def test_default_is_plugins(self) -> None:
        from ida_setup._common import PLUGINS_DIR

        args = argparse.Namespace()
        args.loader = False
        assert _resolve_target_dir(args) == PLUGINS_DIR

    def test_loader_flag(self) -> None:
        from ida_setup._common import LOADERS_DIR

        args = argparse.Namespace()
        args.loader = True
        assert _resolve_target_dir(args) == LOADERS_DIR


# -- cmd_status non-probe tests ----------------------------------------------


class TestCmdStatusNonProbe:
    def _make_status_args(self) -> argparse.Namespace:
        args = _make_args()
        args.probe = False
        args.import_name = []
        return args

    def test_shows_ida_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        from ida_setup._ida import IdaApp

        app = IdaApp(path=Path("/fake/IDA Professional 9.2.app"), version=(9, 2))
        args = self._make_status_args()

        with (
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.get_venv_python_exe", return_value=None),
            patch("ida_setup.cli.read_python3_target_dll", return_value=None),
            patch("ida_setup.cli.resolve_base_prefix", return_value=None),
            patch("ida_setup.cli.PLIST_PATH", Path("/nonexistent")),
            patch("ida_setup.cli.LEGACY_IDALIB_VENV_DIR", Path("/nonexistent")),
        ):
            rc = cmd_status(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "ida:" in out
        assert "9.2" in out

    def test_shows_ida_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = self._make_status_args()

        with (
            patch("ida_setup.cli.resolve_ida_app", side_effect=SystemExit("no IDA")),
            patch("ida_setup.cli.get_venv_python_exe", return_value=None),
            patch("ida_setup.cli.read_python3_target_dll", return_value=None),
            patch("ida_setup.cli.resolve_base_prefix", return_value=None),
            patch("ida_setup.cli.PLIST_PATH", Path("/nonexistent")),
            patch("ida_setup.cli.LEGACY_IDALIB_VENV_DIR", Path("/nonexistent")),
        ):
            rc = cmd_status(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "not found" in out

    def test_shows_venv_present(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from ida_setup._ida import IdaApp

        venv_python = tmp_path / "venv" / "bin" / "python3"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        args = self._make_status_args()

        with (
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.get_venv_python_exe", return_value=venv_python),
            patch("ida_setup.cli.read_python3_target_dll", return_value=None),
            patch("ida_setup.cli.resolve_base_prefix", return_value=None),
            patch("ida_setup.cli.PLIST_PATH", Path("/nonexistent")),
            patch("ida_setup.cli.LEGACY_IDALIB_VENV_DIR", Path("/nonexistent")),
            patch("ida_setup.cli.run", return_value=MagicMock(returncode=0)),
        ):
            rc = cmd_status(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "python:" in out

    def test_shows_python_match(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from ida_setup._ida import IdaApp

        prefix = tmp_path / "python3.12"
        dylib = prefix / "lib" / "libpython3.12.dylib"
        dylib.parent.mkdir(parents=True)
        dylib.touch()
        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        args = self._make_status_args()

        with (
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.get_venv_python_exe", return_value=None),
            patch("ida_setup.cli.read_python3_target_dll", return_value=str(dylib)),
            patch("ida_setup.cli.resolve_base_prefix", return_value=prefix),
            patch("ida_setup.cli.PLIST_PATH", Path("/nonexistent")),
            patch("ida_setup.cli.LEGACY_IDALIB_VENV_DIR", Path("/nonexistent")),
        ):
            rc = cmd_status(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "match: OK" in out

    def test_shows_python_mismatch(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from ida_setup._ida import IdaApp

        prefix = tmp_path / "python3.12"
        prefix.mkdir()
        dylib = tmp_path / "other" / "libpython3.12.dylib"
        dylib.parent.mkdir()
        dylib.touch()
        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        args = self._make_status_args()

        with (
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.get_venv_python_exe", return_value=None),
            patch("ida_setup.cli.read_python3_target_dll", return_value=str(dylib)),
            patch("ida_setup.cli.resolve_base_prefix", return_value=prefix),
            patch("ida_setup.cli.PLIST_PATH", Path("/nonexistent")),
            patch("ida_setup.cli.LEGACY_IDALIB_VENV_DIR", Path("/nonexistent")),
        ):
            rc = cmd_status(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "MISMATCH" in out

    def test_shows_legacy_warning(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from ida_setup._ida import IdaApp

        legacy_dir = tmp_path / "idalib-venv"
        legacy_dir.mkdir()
        app = IdaApp(path=Path("/fake/IDA.app"), version=(9, 2))
        args = self._make_status_args()

        with (
            patch("ida_setup.cli.resolve_ida_app", return_value=app),
            patch("ida_setup.cli.get_venv_python_exe", return_value=None),
            patch("ida_setup.cli.read_python3_target_dll", return_value=None),
            patch("ida_setup.cli.resolve_base_prefix", return_value=None),
            patch("ida_setup.cli.PLIST_PATH", Path("/nonexistent")),
            patch("ida_setup.cli.LEGACY_IDALIB_VENV_DIR", legacy_dir),
        ):
            rc = cmd_status(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "stale" in out
