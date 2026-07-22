"""ida-setup CLI: argparse setup and command handlers."""

import argparse
import contextlib
import io
import os
import sys
from pathlib import Path

from ida_setup._common import (
    _BOLD,
    _DIM,
    _GREEN,
    _RED,
    _YELLOW,
    LOADERS_DIR,
    PLIST_PATH,
    PLUGINS_DIR,
    VENV_DIR,
    _style,
    cfg,
    configure_logging,
    get_venv_python_exe,
    non_interactive_without_yes,
    require_macos,
    resolve_base_prefix,
    resolve_python_for_cli,
    run_pip,
)
from ida_setup._ida import read_ida_config_install_dir, read_python3_target_dll, resolve_ida_app, switch_idapython
from ida_setup._launchagent import (
    get_ida_venv_var,
    install_launch_agent,
    is_launch_agent_loaded,
    is_launch_agent_up_to_date,
)
from ida_setup._plugins import (
    plugins_install,
    plugins_link,
    plugins_list,
    plugins_relink,
    plugins_uninstall,
    plugins_unlink,
)
from ida_setup._probe import run_probe
from ida_setup._run import clean_env_for_python_exec, require_core_tools, run
from ida_setup._venv import (
    install_idapro_package,
    resolve_framework_python,
    run_py_activate_idalib,
    verify_idalib_import,
)

# -- Helpers -----------------------------------------------------------------


def _dylib_matches_prefix(dylib_path: str, prefix: Path) -> bool:
    """Check if a Python dylib path is under the given installation prefix."""
    p = Path(dylib_path)
    resolved = p.resolve() if p.exists() else p
    try:
        resolved.relative_to(prefix)
        return True
    except ValueError:
        return False


def _resolve_default_python(args: argparse.Namespace) -> Path:
    """Resolve --python, falling back to IDAPYTHON_VENV_EXECUTABLE."""
    if args.python is not None:
        return resolve_python_for_cli(
            python_spec=args.python,
            ida_app=args.ida,
            verbose=args.verbose,
        )

    # Check GUI session env var (set by LaunchAgent via launchctl setenv).
    env_val = get_ida_venv_var()
    if not env_val:
        # Fall back to process environment (e.g. user exported it in shell).
        env_val = os.environ.get("IDAPYTHON_VENV_EXECUTABLE", "").strip()

    if env_val:
        exe = Path(env_val)
        if exe.exists() and os.access(exe, os.X_OK):
            return exe

    raise SystemExit(
        "no Python interpreter specified.\n\n"
        "Use one of:\n"
        "  --python ida       probe IDA and use its interpreter\n"
        "  --python <path>    explicit path to a python executable\n\n"
        "Or set up a LaunchAgent (ida-setup venv) so\n"
        "IDAPYTHON_VENV_EXECUTABLE is available in your environment."
    )


# -- Command handlers --------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    import_names = [str(x) for x in args.import_name]
    if import_names and not args.probe:
        raise SystemExit("--import requires --probe")

    if args.probe:
        app = resolve_ida_app(args.ida)
        return run_probe(
            app=app,
            import_names=import_names,
            print_json=bool(args.verbose),
        )

    chosen = None
    try:
        chosen = resolve_ida_app(None)
        ver = ".".join(str(x) for x in chosen.version)
        print(f"{_style(_BOLD, 'ida:')} {chosen.path} {_style(_DIM, f'(version {ver})')}")
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        print(f"{_style(_BOLD, 'ida:')} {_style(_RED, 'not found')}")

    # Venv
    print(f"\n{_style(_BOLD, 'venv')}")
    venv_python = get_venv_python_exe()
    if venv_python and venv_python.exists():
        print(f"  path:   {_style(_DIM, str(VENV_DIR))}")
        print(f"  python: {_style(_DIM, str(venv_python))}")
    else:
        print(f"  {_style(_RED, 'not found')} {_style(_DIM, f'({VENV_DIR})')}")

    # Python mismatch: compare IDA's idapyswitch dylib vs venv's base python.
    # Resolves symlinks on both sides so Homebrew opt/Cellar, pyenv, framework
    # paths all compare correctly without per-distro regex matching.
    print(f"\n{_style(_BOLD, 'python')}")
    ida_dll = read_python3_target_dll()
    venv_prefix = resolve_base_prefix(VENV_DIR)

    if ida_dll and venv_prefix:
        if _dylib_matches_prefix(ida_dll, venv_prefix):
            print(f"  path:  {_style(_DIM, ida_dll)}")
            print(f"  match: {_style(_GREEN, 'OK')}")
        else:
            print(f"  ida:   {_style(_DIM, ida_dll)}")
            print(f"  venv:  {_style(_DIM, str(venv_prefix))}")
            print(f"  match: {_style(_RED, 'MISMATCH')}")
            print(f"  {_style(_YELLOW, 'fix: ida-setup venv')}")
    else:
        print(f"  ida:  {_style(_DIM, ida_dll or '(unknown)')}")
        print(f"  venv: {_style(_DIM, str(venv_prefix) if venv_prefix else '(unknown)')}")

    # LaunchAgent
    print(f"\n{_style(_BOLD, 'launchagent')}")
    if PLIST_PATH.exists():
        loaded = is_launch_agent_loaded()
        print(f"  plist:  {_style(_DIM, str(PLIST_PATH))}")
        loaded_val = _style(_GREEN, "yes") if loaded else _style(_RED, "no")
        print(f"  loaded: {loaded_val}")
        var = get_ida_venv_var()
        print(f"  IDAPYTHON_VENV_EXECUTABLE: {_style(_DIM, var or '(not set)')}")
        if venv_python:
            up_to_date = is_launch_agent_up_to_date(venv_python)
            utd_val = _style(_GREEN, "yes") if up_to_date else _style(_RED, "no")
            print(f"  up-to-date: {utd_val}")
    else:
        print(f"  {_style(_RED, 'not installed')}")

    # idalib (checked within the shared venv)
    print(f"\n{_style(_BOLD, 'idalib')}")
    if venv_python and venv_python.exists():
        res = run(
            [str(venv_python), "-c", "import idapro; print('ok')"],
            check=False,
            capture=True,
            env=clean_env_for_python_exec(),
        )
        if res.returncode == 0:
            print(f"  import idapro: {_style(_GREEN, 'ok')}")
            # Stale ida-config.json: install dir points to a different IDA version.
            config_dir = read_ida_config_install_dir()
            if chosen is not None and config_dir is not None:
                if config_dir != chosen.install_dir:
                    print(f"  {_style(_RED, 'stale ida-config.json:')} {_style(_DIM, str(config_dir))}")
                    print(f"    current IDA: {_style(_DIM, str(chosen.install_dir))}")
                    print(f"  {_style(_YELLOW, 'fix: ida-setup venv')}")
        else:
            print(f"  import idapro: {_style(_RED, 'FAILED')}")
            print(f"  {_style(_YELLOW, 'fix: ida-setup venv')}")
    else:
        print(f"  {_style(_DIM, 'skipped (no venv)')}")

    return 0


def cmd_venv(args: argparse.Namespace) -> int:
    """Create or update ~/.idapro/venv: install idapro, activate idalib, set up LaunchAgent."""
    # Check if already exists.
    venv_python = get_venv_python_exe()
    if venv_python:
        print(f"{_style(_BOLD, 'venv:')} already exists at {_style(_DIM, str(VENV_DIR))}")
        print(f"{_style(_BOLD, 'python:')} {_style(_DIM, str(venv_python))}")
    else:
        # Resolve base python — --python is required for creation.
        if args.python is None:
            raise SystemExit(
                "a base Python interpreter is required to create the venv.\n\n"
                "Usage:\n"
                "  ida-setup venv --python /path/to/python3\n\n"
                "Example:\n"
                '  ida-setup venv --python "$(pyenv which python)"'
            )
        if args.python == "ida":
            raise SystemExit(
                "--python ida cannot be used with venv.\n"
                "IDA's embedded Python reports the IDA binary as sys.executable\n"
                "when no venv is active.\n\n"
                "Use an explicit path:\n"
                "  ida-setup venv --python /path/to/python3"
            )

        base_python = resolve_python_for_cli(
            python_spec=args.python,
            ida_app=args.ida,
            verbose=args.verbose,
        )
        # make sure we are able to resolve the framework before creating venv
        resolve_framework_python(base_python)

        print(f"{_style(_BOLD, 'venv:')} creating at {_style(_DIM, str(VENV_DIR))}")
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(["uv", "venv", str(VENV_DIR), "--seed", "--python", str(base_python)], env=clean_env_for_python_exec())

        venv_python = get_venv_python_exe()
        if venv_python is None:
            raise SystemExit(f"venv python not found after creation: {VENV_DIR}")

        print(f"{_style(_BOLD, 'python:')} {_style(_DIM, str(venv_python))}")

    # Install/upgrade idapro and activate idalib.
    app = resolve_ida_app(args.ida)
    install_idapro_package(app=app, venv_python=venv_python)

    run_py_activate_idalib(app=app, venv_python=venv_python)

    verify_idalib_import(venv_python)

    framework_python = resolve_framework_python(venv_python)
    switch_idapython(app=app, python_library=framework_python)

    print()
    _offer_launchagent(venv_python=venv_python)

    return 0


def _offer_launchagent(*, venv_python: Path) -> None:
    """Set up the LaunchAgent, skipping if already current."""
    if is_launch_agent_loaded() and is_launch_agent_up_to_date(venv_python) and get_ida_venv_var() == str(venv_python):
        print(f"{_style(_BOLD, 'launchagent:')} {_style(_GREEN, 'up to date')}")
        return

    if cfg.yes:
        # Non-interactive: just do it.
        install_launch_agent(venv_python_exe=venv_python)
        return

    if non_interactive_without_yes():
        raise SystemExit("non-interactive session; pass --yes to also configure the LaunchAgent.")

    ans = input(
        "Set up a LaunchAgent so Finder-launched IDA uses this venv?\n"
        "(Sets IDAPYTHON_VENV_EXECUTABLE in your GUI session) [Y/n] "
    ).strip().lower()  # fmt: skip

    if ans in {"", "y", "yes"}:
        install_launch_agent(venv_python_exe=venv_python)
    else:
        print(_style(_DIM, "skipped. You can run `ida-setup venv` later."))


def _resolve_target_dir(args: argparse.Namespace) -> Path:
    """Return LOADERS_DIR if --loader is set, else PLUGINS_DIR."""
    if args.loader:
        return LOADERS_DIR
    return PLUGINS_DIR


def cmd_plugins_list(args: argparse.Namespace) -> int:
    return plugins_list()


def cmd_plugins_link(args: argparse.Namespace) -> int:
    return plugins_link(sources=[Path(s) for s in args.source], target_dir=_resolve_target_dir(args), force=args.force)


def cmd_plugins_unlink(args: argparse.Namespace) -> int:
    return plugins_unlink(names=args.name, target_dir=_resolve_target_dir(args), force=args.force)


def cmd_plugins_install(args: argparse.Namespace) -> int:
    python_exe = _resolve_default_python(args)
    pip_args = list(args._passthrough)
    if not pip_args:
        raise SystemExit("usage: ida-setup plugin install <pip args>\n\nexample: ida-setup plugin install keypatch")
    return plugins_install(pip_args=pip_args, python_exe=python_exe)


def cmd_plugins_uninstall(args: argparse.Namespace) -> int:
    python_exe = _resolve_default_python(args)
    return plugins_uninstall(pkg_names=args.pkg, python_exe=python_exe)


def cmd_plugins_relink(args: argparse.Namespace) -> int:
    python_exe = _resolve_default_python(args)
    return plugins_relink(python_exe=python_exe, pkg_name=args.pkg)


def cmd_pip(args: argparse.Namespace) -> int:
    """Run pip using the selected interpreter."""
    pip_args = list(args._passthrough)
    if not pip_args:
        pip_args = ["--help"]

    python_exe = _resolve_default_python(args)
    return run_pip(python_exe=python_exe, pip_args=pip_args)


def cmd_python(args: argparse.Namespace) -> int:
    """Run python using the selected interpreter."""
    python_args = list(args._passthrough)
    python_exe = _resolve_default_python(args)
    res = run([str(python_exe), *python_args], check=False, env=clean_env_for_python_exec(), dim=False)
    return int(res.returncode)


# -- Argument parsing --------------------------------------------------------


def _is_passthrough_command(args: argparse.Namespace) -> bool:
    """Return true if parsed args select a passthrough command."""
    return args.cmd in {"pip", "python"} or (args.cmd == "plugin" and getattr(args, "plugin_cmd", None) == "install")


def _parse_passthrough_prefix(
    parser: argparse.ArgumentParser,
    argv: list[str],
) -> tuple[argparse.Namespace, list[str]] | None:
    """Parse a validated command prefix and keep the raw passthrough tail."""
    for index, token in enumerate(argv):
        if token not in {"pip", "python", "install"}:
            continue

        boundary = index + 1
        # Invalid candidate prefixes are expected; argparse prints before raising SystemExit.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                args = parser.parse_args(argv[:boundary])
            except SystemExit:
                continue

        if _is_passthrough_command(args):
            return args, argv[boundary:]

    return None


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS, help="Verbose logging")
    common.add_argument("--yes", action="store_true", default=argparse.SUPPRESS, help="Do not prompt")
    common.add_argument(
        "--ida",
        default=argparse.SUPPRESS,
        help="Path to 'IDA Professional X.Y.app'. Default: auto-detect via Spotlight and pick newest.",
    )
    common.add_argument(
        "--python",
        default=argparse.SUPPRESS,
        help="Python interpreter to use: '/path/to/python' or 'ida' to probe IDA. Default: from LaunchAgent if set up.",
    )

    parser = argparse.ArgumentParser(
        prog="ida-setup",
        description="IDA Pro Python environment toolkit for macOS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # status
    p_status = sub.add_parser("status", help="Show overall setup state", parents=[common])
    p_status.add_argument(
        "--probe", action="store_true", default=False, help="Launch IDA and report its Python runtime"
    )
    p_status.add_argument(
        "--import",
        action="append",
        default=[],
        dest="import_name",
        help="Import to verify inside IDA (requires --probe, repeatable)",
    )
    p_status.set_defaults(func=cmd_status)

    # venv
    p_venv = sub.add_parser(
        "venv",
        help="Create or update the IDA venv, install idapro, activate idalib, set up LaunchAgent",
        parents=[common],
    )
    p_venv.set_defaults(func=cmd_venv)

    # plugin
    p_plugin = sub.add_parser("plugin", help="Manage plugins and loaders", parents=[common])
    plugin_sub = p_plugin.add_subparsers(dest="plugin_cmd", required=True)

    p_plugin_list = plugin_sub.add_parser("list", help="List ~/.idapro/plugins and loaders", parents=[common])
    p_plugin_list.set_defaults(func=cmd_plugins_list)

    p_plugin_link = plugin_sub.add_parser(
        "link", help="Symlink sources into ~/.idapro/plugins (or loaders with --loader)", parents=[common]
    )
    p_plugin_link.add_argument("source", nargs="+", help="File or directory to symlink")
    p_plugin_link.add_argument(
        "--loader", action="store_true", default=False, help="Target ~/.idapro/loaders instead of plugins"
    )
    p_plugin_link.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Allow overwriting/deleting real files and directories",
    )
    p_plugin_link.set_defaults(func=cmd_plugins_link)

    p_plugin_unlink = plugin_sub.add_parser(
        "unlink", help="Remove symlinks from ~/.idapro/plugins (or loaders with --loader)", parents=[common]
    )
    p_plugin_unlink.add_argument("name", nargs="+", help="Name in target directory")
    p_plugin_unlink.add_argument(
        "--loader", action="store_true", default=False, help="Target ~/.idapro/loaders instead of plugins"
    )
    p_plugin_unlink.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Allow deleting real files and directories (not just symlinks)",
    )
    p_plugin_unlink.set_defaults(func=cmd_plugins_unlink)

    p_plugin_install = plugin_sub.add_parser(
        "install",
        help="Install a package and symlink its ida_plugins/ida_loaders entry points",
        description=(
            "Install a package via uv pip and symlink any new ida_plugins/ida_loaders\n"
            "entry points into ~/.idapro/plugins and ~/.idapro/loaders.\n\n"
            "All arguments after 'install' are forwarded to `uv pip install`."
        ),
        parents=[common],
    )
    p_plugin_install.set_defaults(func=cmd_plugins_install)
    # Append [pip-args ...] to the auto-generated usage.
    p_plugin_install.usage = p_plugin_install.format_usage().removeprefix("usage: ").rstrip() + " [pip-args ...]"

    p_plugin_uninstall = plugin_sub.add_parser(
        "uninstall",
        help="Uninstall packages and remove their ida_plugins/ida_loaders entry points",
        parents=[common],
    )
    p_plugin_uninstall.add_argument("pkg", nargs="+", help="Package to uninstall")
    p_plugin_uninstall.set_defaults(func=cmd_plugins_uninstall)

    p_plugin_relink = plugin_sub.add_parser(
        "relink",
        help="Recreate ida_plugins/ida_loaders entry point symlinks",
        parents=[common],
    )
    p_plugin_relink.add_argument("pkg", nargs="?", help="Only relink entry points from this package")
    p_plugin_relink.set_defaults(func=cmd_plugins_relink)

    # pip / python
    p_pip = sub.add_parser("pip", help="Run pip using the selected interpreter", add_help=False, parents=[common])
    p_pip.set_defaults(func=cmd_pip)

    p_python = sub.add_parser(
        "python", help="Run python using the selected interpreter", add_help=False, parents=[common]
    )
    p_python.set_defaults(func=cmd_python)

    passthrough_parse = _parse_passthrough_prefix(parser, argv_list)
    if passthrough_parse is None:
        args, passthrough = parser.parse_known_args(argv_list)
    else:
        args, passthrough = passthrough_parse

    # Fill in suppressed defaults.
    if not hasattr(args, "verbose"):
        args.verbose = False
    if not hasattr(args, "yes"):
        args.yes = False
    if not hasattr(args, "ida"):
        args.ida = None
    if not hasattr(args, "python"):
        args.python = None

    configure_logging(bool(args.verbose))
    require_macos()

    passthrough_cmd = args.cmd in {"pip", "python"} or (args.cmd == "plugin" and args.plugin_cmd == "install")

    if not passthrough_cmd and passthrough:
        parser.error("unrecognized arguments: " + " ".join(passthrough))

    args._passthrough = passthrough if passthrough_cmd else []

    require_core_tools()

    cfg.yes = bool(args.yes)

    return int(args.func(args))


def main_cli() -> int:
    """Entry point for console_scripts and `python -m ida_setup`."""
    try:
        return main()
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main_cli())
