"""Plugin and loader management for ~/.idapro."""

import json
import logging
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


def _get_managed_targets() -> dict[str, dict[str, str]]:
    """Resolve entry point targets from the venv.

    Returns {"plugins": {resolved_path: dist_name, ...}, "loaders": {...}}.
    Returns empty dicts if the venv is missing or broken.
    """
    empty: dict[str, dict[str, str]] = {"plugins": {}, "loaders": {}}
    venv_python = get_venv_python_exe()
    if not venv_python:
        return empty
    try:
        ep = _discover_entrypoints(venv_python)
    except Exception:
        LOG.debug("entry point discovery failed; treating all as manual", exc_info=True)
        return empty
    result: dict[str, dict[str, str]] = {}
    for key in ("plugins", "loaders"):
        result[key] = {
            str(Path(info["origin"]).resolve()): info.get("dist") or "unknown" for info in ep.get(key, {}).values()
        }
    return result


def _list_dir(target_dir: Path, kind: str, managed_targets: dict[str, str]) -> None:
    """List entries in a single directory."""
    print(f"{_style(_BOLD, kind)}: {_style(_DIM, str(target_dir))}")

    if not target_dir.exists():
        print(f"  {_style(_RED, '(missing)')}")
        return

    ignored = {"__pycache__", ".DS_Store"}
    entries = sorted((p for p in target_dir.iterdir() if p.name not in ignored), key=lambda p: p.name)
    if not entries:
        print(f"  {_style(_DIM, '(empty)')}")
        return

    for p in entries:
        if p.is_symlink():
            try:
                resolved = str(p.resolve(strict=True))
                dist_name = managed_targets.get(resolved)
                if dist_name:
                    name_col = _style(_BOLD_GREEN, p.name)
                    tag = _style(_CYAN, f"[{dist_name}]")
                else:
                    name_col = _style(_GREEN, p.name)
                    tag = ""
                target_col = _style(_DIM, resolved)
            except FileNotFoundError:
                tag = ""
                name_col = _style(_RED, p.name)
                target_col = _style(_RED, "(broken)")
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
            print(f"  {p.name} {_style(_DIM, '(file)')}")


def plugins_list() -> int:
    """List plugins and loaders."""
    managed = _get_managed_targets()
    _list_dir(PLUGINS_DIR, "plugins", managed["plugins"])
    print()
    _list_dir(LOADERS_DIR, "loaders", managed["loaders"])
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
        [str(python_exe), "-c", _DISCOVER_SCRIPT],
        check=True,
        capture=True,
        env=clean_env_for_python_exec(),
    )
    return json.loads(res.stdout)


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


def plugins_relink(*, python_exe: Path) -> int:
    """Recreate all ida_plugins/ida_loaders entry point symlinks."""
    ep = _discover_entrypoints(python_exe)

    plugins = ep.get("plugins", {})
    loaders = ep.get("loaders", {})

    if plugins:
        linked = _link_entrypoints(plugins, PLUGINS_DIR, "_plugin")
        for path in linked:
            print(f"{_style(_BOLD, 'plugin:')} {_style(_DIM, path)}")

    if loaders:
        linked = _link_entrypoints(loaders, LOADERS_DIR, "_loader")
        for path in linked:
            print(f"{_style(_BOLD, 'loader:')} {_style(_DIM, path)}")

    if not plugins and not loaders:
        print(_style(_DIM, "no ida_plugins or ida_loaders entry points found"))
    else:
        print(_style(_GREEN, "ok: relinked"))

    return 0
