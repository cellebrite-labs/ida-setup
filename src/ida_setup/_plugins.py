"""Plugin and loader management for ~/.idapro."""

import json
import logging
import re
import shutil
import textwrap
from pathlib import Path

from ida_setup._common import (
    _BOLD,
    _BOLD_GREEN,
    _CYAN,
    _DIM,
    _GREEN,
    _RED,
    LOADERS_DIR,
    PLUGINS_DIR,
    _style,
    get_venv_python_exe,
)
from ida_setup._run import clean_env_for_python_exec, run

LOG = logging.getLogger(__name__)
LOADABLE_ENTRY_SUFFIXES = {".py", ".dylib", ".so", ".dll"}


def _is_loadable_entry_name(name: str) -> bool:
    """Return true if IDA can load an entry by filename."""
    return Path(name).suffix.lower() in LOADABLE_ENTRY_SUFFIXES


def validate_entry_name(name: str) -> str:
    """Validate a plugin/loader name (no paths/traversal)."""
    if not name:
        raise SystemExit("name must not be empty")
    if name != Path(name).name or "/" in name or "\\" in name:
        raise SystemExit(f"invalid name (name only, no paths): {name}")
    return name


def remove_existing_target(*, target: Path, force: bool) -> None:
    """Remove an existing target. Removing a non-symlink requires --force."""
    if not target.is_symlink() and not force:
        raise SystemExit(f"refusing to remove a real file/directory without --force: {target}")

    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink(missing_ok=True)


def _get_managed_targets() -> dict[str, dict[str, dict[str, str]]]:
    """Resolve entry point targets from the venv.

    Returns {"plugins": {entry_name: {"origin": resolved_path, "dist": dist_name}, ...}, "loaders": {...}}.
    Returns empty dicts if the venv is missing or broken.
    """
    empty: dict[str, dict[str, dict[str, str]]] = {"plugins": {}, "loaders": {}}
    venv_python = get_venv_python_exe()
    if not venv_python:
        return empty
    try:
        ep = _discover_entrypoints(venv_python)
    except Exception:
        LOG.debug("entry point discovery failed; treating all as manual", exc_info=True)
        return empty
    result: dict[str, dict[str, dict[str, str]]] = {}
    for key in ("plugins", "loaders"):
        result[key] = {
            name: {"origin": str(Path(info["origin"]).resolve()), "dist": info.get("dist") or "unknown"}
            for name, info in ep.get(key, {}).items()
        }
    return result


def _expected_entrypoint_links(managed_targets: dict[str, dict[str, str]], suffix: str) -> dict[str, dict[str, str]]:
    """Return expected link filenames for managed entry points."""
    return {f"{name}{suffix}.py": info for name, info in managed_targets.items()}


def _list_dir(target_dir: Path, kind: str, managed_targets: dict[str, dict[str, str]], suffix: str) -> None:
    """List entries in a single directory."""
    print(f"{_style(_BOLD, kind)}: {_style(_DIM, str(target_dir))}")

    ignored = {"__pycache__", ".DS_Store"}
    entries_by_name: dict[str, Path] = {}
    if target_dir.exists():
        entries_by_name = {p.name: p for p in target_dir.iterdir() if p.name not in ignored}
    else:
        print(f"  {_style(_RED, '(missing)')}")

    managed_by_origin = {info["origin"]: info["dist"] for info in managed_targets.values()}
    expected_links = _expected_entrypoint_links(managed_targets, suffix)
    missing_links = {
        name: info
        for name, info in expected_links.items()
        if name not in entries_by_name and not (target_dir / name).is_symlink()
    }

    if not entries_by_name and not missing_links:
        if target_dir.exists():
            print(f"  {_style(_DIM, '(empty)')}")
        return

    for name in sorted({*entries_by_name, *missing_links}):
        if name in missing_links:
            info = missing_links[name]
            warning_code = f"{_BOLD};{_RED}"
            name_col = _style(warning_code, name)
            state_col = _style(warning_code, "(missing)")
            target_col = _style(_RED, info["origin"])
            tag = _style(_CYAN, f"[{info['dist']}]")
            print(f"  {name_col} {state_col} {_style(_DIM, '->')} {target_col} {tag}")
            continue

        p = entries_by_name[name]
        if p.is_symlink():
            try:
                resolved = str(p.resolve(strict=True))
                dist_name = managed_by_origin.get(resolved)
                if dist_name:
                    name_col = _style(_BOLD_GREEN, p.name) if _is_loadable_entry_name(p.name) else p.name
                    tag = _style(_CYAN, f"[{dist_name}]")
                else:
                    name_col = _style(_GREEN, p.name) if _is_loadable_entry_name(p.name) else p.name
                    tag = ""
                target_col = _style(_DIM, resolved)
                parts = [f"  {name_col}", f"{_style(_DIM, '->')} {target_col}"]
            except FileNotFoundError:
                tag = ""
                name_col = _style(_RED, p.name)
                broken_target = p.readlink()
                if not broken_target.is_absolute():
                    broken_target = p.parent / broken_target
                target_col = _style(_RED, str(broken_target))
                parts = [f"  {name_col}", f"{_style(_DIM, '->')} {target_col}", _style(_RED, "(broken)")]
            except Exception:
                tag = ""
                name_col = _style(_RED, p.name)
                target_col = _style(_RED, "(unresolvable)")
                parts = [f"  {name_col}", f"{_style(_DIM, '->')} {target_col}"]
            if tag:
                parts.append(tag)
            print(" ".join(parts))
        elif p.is_dir():
            print(f"  {p.name} {_style(_DIM, '(dir)')}")
        else:
            name_col = _style(_GREEN, p.name) if _is_loadable_entry_name(p.name) else p.name
            print(f"  {name_col} {_style(_DIM, '(file)')}")


def plugins_list() -> int:
    """List plugins and loaders."""
    managed = _get_managed_targets()
    _list_dir(PLUGINS_DIR, "plugins", managed["plugins"], "_plugin")
    print()
    _list_dir(LOADERS_DIR, "loaders", managed["loaders"], "_loader")
    return 0


def plugins_link(*, sources: list[Path], target_dir: Path, force: bool) -> int:
    """Symlink sources into target directory."""
    if not sources:
        raise SystemExit("link requires at least one --source")

    target_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        source = source.expanduser().resolve()
        if not source.exists():
            raise SystemExit(f"plugin source does not exist: {source}")

        target = target_dir / source.name

        if target.exists() or target.is_symlink():
            try:
                if target.is_symlink() and target.resolve() == source.resolve():
                    continue
            except Exception:
                pass

            if not force:
                kind = "symlink" if target.is_symlink() else "real file/dir"
                raise SystemExit(f"refusing to overwrite existing {kind} without --force: {target}")

            remove_existing_target(target=target, force=force)

        target.symlink_to(source)

    print(_style(_GREEN, "ok: linked"))
    return 0


def plugins_unlink(*, names: list[str], target_dir: Path, force: bool) -> int:
    """Remove entries from target directory."""
    validated = [validate_entry_name(x) for x in names]
    if not validated:
        raise SystemExit("unlink requires at least one --name")

    if not target_dir.exists():
        raise SystemExit(f"directory does not exist: {target_dir}")

    targets = [(name, target_dir / name) for name in validated]

    # Fail fast before doing anything.
    for name, target in targets:
        if not (target.exists() or target.is_symlink()):
            raise SystemExit(f"plugin not found: {name}")
        if not target.is_symlink() and not force:
            raise SystemExit(f"refusing to remove a real file/directory without --force: {target}")

    for _, target in targets:
        if target.is_symlink():
            target.unlink(missing_ok=True)
            continue

        remove_existing_target(target=target, force=force)

    print(_style(_GREEN, "ok: unlinked"))
    return 0


# -- Entry-point based install -----------------------------------------------

# Script executed in the target venv to discover ida_plugins / ida_loaders entry points.
_DISCOVER_SCRIPT = textwrap.dedent("""\
    import importlib.metadata
    import importlib.util
    import json
    import sys

    result = {"plugins": {}, "loaders": {}}
    for group, key in [("ida_plugins", "plugins"), ("ida_loaders", "loaders")]:
        for ep in importlib.metadata.entry_points(group=group):
            spec = importlib.util.find_spec(ep.module)
            if spec and spec.origin:
                dist_name = ep.dist.name if ep.dist else None
                result[key][ep.name] = {"origin": spec.origin, "dist": dist_name}
    json.dump(result, sys.stdout)
""")


def _discover_entrypoints(python_exe: Path) -> dict[str, dict[str, dict[str, str | None]]]:
    """Run discovery script in the target interpreter and return entry points."""
    res = run(
        [str(python_exe), "-I", "-c", _DISCOVER_SCRIPT],
        check=True,
        capture=True,
        env=clean_env_for_python_exec(),
    )
    return json.loads(res.stdout)


def _normalize_pkg_name(name: str) -> str:
    """Normalize a Python distribution name for comparison."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _filter_entrypoints_by_dist(
    entries: dict[str, dict[str, str | None]], pkg_name: str
) -> dict[str, dict[str, str | None]]:
    """Return entry points owned by the requested distribution."""
    normalized_pkg_name = _normalize_pkg_name(pkg_name)
    return {
        name: info
        for name, info in entries.items()
        if info["dist"] is not None and _normalize_pkg_name(info["dist"]) == normalized_pkg_name
    }


def _link_entrypoints(entries: dict[str, dict[str, str | None]], target_dir: Path, suffix: str) -> list[str]:
    """Symlink discovered entry point modules into target_dir with the given suffix."""
    linked: list[str] = []
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, info in entries.items():
        origin_path = Path(info["origin"])
        link_path = target_dir / f"{name}{suffix}.py"
        # exists() is false for broken symlinks.
        if link_path.exists() or link_path.is_symlink():
            if not link_path.is_symlink():
                raise SystemExit(f"refusing to overwrite real file/directory: {link_path}")
            link_path.unlink()
        link_path.symlink_to(origin_path)
        linked.append(str(link_path))
    return linked


def _unlink_entrypoint_links(entries: dict[str, dict[str, str | None]], target_dir: Path, suffix: str) -> list[str]:
    """Remove symlinks for discovered entry point modules from target_dir."""
    unlinked: list[str] = []
    if not target_dir.exists():
        return unlinked

    for name in entries:
        link_path = target_dir / f"{name}{suffix}.py"
        # exists() is false for broken symlinks.
        if not (link_path.exists() or link_path.is_symlink()):
            continue
        if not link_path.is_symlink():
            raise SystemExit(f"refusing to remove real file/directory: {link_path}")
        link_path.unlink()
        unlinked.append(str(link_path))
    return unlinked


def plugins_install(*, pip_args: list[str], python_exe: Path) -> int:
    """Install a plugin package and symlink its ida_plugins/ida_loaders entry points."""
    env = clean_env_for_python_exec()

    # Snapshot entry points before install.
    before = _discover_entrypoints(python_exe)

    # Install the package into the target interpreter's environment.
    run(["uv", "pip", "install", *pip_args, "--python", str(python_exe)], check=True, env=env)

    # Snapshot after install; only link new or changed entry points.
    after = _discover_entrypoints(python_exe)

    to_link_plugins = {k: v for k, v in after.get("plugins", {}).items() if before.get("plugins", {}).get(k) != v}
    to_link_loaders = {k: v for k, v in after.get("loaders", {}).items() if before.get("loaders", {}).get(k) != v}

    if to_link_plugins:
        linked = _link_entrypoints(to_link_plugins, PLUGINS_DIR, "_plugin")
        for path in linked:
            print(f"{_style(_BOLD, 'plugin:')} {_style(_DIM, path)}")

    if to_link_loaders:
        linked = _link_entrypoints(to_link_loaders, LOADERS_DIR, "_loader")
        for path in linked:
            print(f"{_style(_BOLD, 'loader:')} {_style(_DIM, path)}")

    if not to_link_plugins and not to_link_loaders:
        print(_style(_DIM, "no new ida_plugins or ida_loaders entry points found"))
    else:
        print(_style(_GREEN, "ok: installed"))

    return 0


def plugins_uninstall(*, pkg_names: list[str], python_exe: Path) -> int:
    """Uninstall plugin packages and remove their entry points."""
    env = clean_env_for_python_exec()

    before = _discover_entrypoints(python_exe)
    run(["uv", "pip", "uninstall", *pkg_names, "--python", str(python_exe)], check=True, env=env)
    after = _discover_entrypoints(python_exe)

    to_unlink_plugins = {k: v for k, v in before.get("plugins", {}).items() if k not in after.get("plugins", {})}
    to_unlink_loaders = {k: v for k, v in before.get("loaders", {}).items() if k not in after.get("loaders", {})}

    if to_unlink_plugins:
        unlinked = _unlink_entrypoint_links(to_unlink_plugins, PLUGINS_DIR, "_plugin")
        for path in unlinked:
            print(f"{_style(_BOLD, 'plugin:')} {_style(_DIM, path)}")

    if to_unlink_loaders:
        unlinked = _unlink_entrypoint_links(to_unlink_loaders, LOADERS_DIR, "_loader")
        for path in unlinked:
            print(f"{_style(_BOLD, 'loader:')} {_style(_DIM, path)}")

    if not to_unlink_plugins and not to_unlink_loaders:
        print(_style(_DIM, "no ida_plugins or ida_loaders entry points removed"))
    else:
        print(_style(_GREEN, "ok: uninstalled"))

    return 0


def plugins_relink(*, python_exe: Path, pkg_name: str | None = None) -> int:
    """Recreate ida_plugins/ida_loaders entry point symlinks."""
    ep = _discover_entrypoints(python_exe)

    plugins = ep.get("plugins", {})
    loaders = ep.get("loaders", {})
    if pkg_name is not None:
        plugins = _filter_entrypoints_by_dist(plugins, pkg_name)
        loaders = _filter_entrypoints_by_dist(loaders, pkg_name)

    if plugins:
        linked = _link_entrypoints(plugins, PLUGINS_DIR, "_plugin")
        for path in linked:
            print(f"{_style(_BOLD, 'plugin:')} {_style(_DIM, path)}")

    if loaders:
        linked = _link_entrypoints(loaders, LOADERS_DIR, "_loader")
        for path in linked:
            print(f"{_style(_BOLD, 'loader:')} {_style(_DIM, path)}")

    if not plugins and not loaders:
        if pkg_name is None:
            print(_style(_DIM, "no ida_plugins or ida_loaders entry points found"))
        else:
            print(_style(_DIM, f"no ida_plugins or ida_loaders entry points found for {pkg_name}"))
    else:
        print(_style(_GREEN, "ok: relinked"))

    return 0
