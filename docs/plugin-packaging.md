# Plugin packaging

## Motivation

IDA plugins are Python files (or compiled libraries) placed in `~/.idapro/plugins`. Loaders go in `~/.idapro/loaders`. Traditionally, installing a plugin means cloning a repo and manually copying or symlinking files into the right directory — with no dependency management, no versioning, and no upgrade path.

Hex-Rays introduced their own plugin manager (`hcli`) with a centralized plugin repository and a custom metadata format (`ida-plugin.json`). This format overlaps heavily with what `pyproject.toml` already provides: name, version, description, dependencies, entry points. The `pyproject.toml` ecosystem is an order of magnitude more mature, widely supported by tooling (pip, uv, build backends), and already used by most Python projects.

`ida-setup plugin install` takes a different approach: use standard Python packaging as-is. A plugin is a normal Python package that declares its entry point modules in `pyproject.toml`. The tool installs the package (via `uv pip install`) and symlinks the entry point modules into the appropriate IDA directory. No custom metadata, no centralized repository — any source that `uv pip install` supports works: PyPI, a git URL, a local path, a private index.

## How it works

The mechanism has three parts:

1. The plugin author declares entry points in `pyproject.toml` under the `ida_plugins` and/or `ida_loaders` groups.
2. `ida-setup plugin install` runs `uv pip install` into the IDA venv, then inspects the installed package's entry points.
3. For each new entry point, the tool resolves the module's source file and symlinks it into `~/.idapro/plugins` or `~/.idapro/loaders`.

The symlink approach means IDA sees a regular `.py` file in its plugins/loaders directory, which is exactly what it expects. The actual module lives in the venv's site-packages, so imports and dependencies resolve normally.

## Packaging a plugin

A plugin package needs two things: a standard `pyproject.toml` and an entry point declaration.

### Entry point groups

Two entry point groups are recognized:

- `ida_plugins` — modules symlinked into `~/.idapro/plugins`
- `ida_loaders` — modules symlinked into `~/.idapro/loaders`

### pyproject.toml example

A minimal plugin package:

```toml
[project]
name = "keypatch"
version = "1.0.0"
dependencies = ["keystone-engine"]

[project.entry-points."ida_plugins"]
keypatch = "keypatch.keypatch"
```

The entry point value is a dotted module path (e.g. `keypatch.keypatch` resolves to `keypatch/keypatch.py` in the installed package). The entry point name (`keypatch` on the left side) becomes part of the symlink filename.

A package can declare multiple entry points across both groups:

```toml
[project.entry-points."ida_plugins"]
my_plugin = "my_package.plugin_module"

[project.entry-points."ida_loaders"]
my_loader = "my_package.loader_module"
```

### Entry point semantics

IDA plugins use a file as their entry point — IDA loads the entire `.py` file and looks for `PLUGIN_ENTRY`, `PLUGIN_HOTKEY`, etc. at module level. This differs from the typical Python entry point convention where the value points to a callable (`module:function`).

For IDA entry points, the `attr` part is omitted. The value is just the module path. The tool resolves the module's `__file__` (its source `.py` file) and creates a symlink to it.

### Naming convention

The symlink name is derived from the entry point name with a suffix:

- `ida_plugins` entries get `_plugin.py` appended → `keypatch` becomes `keypatch_plugin.py`
- `ida_loaders` entries get `_loader.py` appended → `iboot` becomes `iboot_loader.py`

This avoids collisions with other files in the directory and makes entry-point-managed symlinks easy to identify.

## Installing plugins

Install from any source `uv pip install` supports:

```bash
# From PyPI
ida-setup plugin install keypatch

# From a git URL
ida-setup plugin install git+https://github.com/user/repo.git
ida-setup plugin install git+ssh://git@github.com/user/repo.git

# From a local directory (editable)
ida-setup plugin install -e /path/to/keypatch

# With version constraints
ida-setup plugin install "keypatch>=2.0"

# Multiple packages
ida-setup plugin install keypatch ipyida
```

All arguments after `install` are forwarded directly to `uv pip install`, so flags like `--index-url`, `--extra-index-url`, `--no-deps`, etc. all work.

The tool snapshots entry points before and after installation, and only creates symlinks for new or changed entries. This makes re-running `plugin install` safe and idempotent for existing plugins.

## Managing symlinks

`plugin list` shows all entries in `~/.idapro/plugins` and `~/.idapro/loaders`, distinguishing symlinks (with their targets), broken symlinks, missing entry-point links, regular files, and directories. Entry-point-managed symlinks are shown in bold with the package name (e.g. `[keypatch]`); manually created symlinks have no tag.

`plugin uninstall` uninstalls a package and removes its `ida_plugins`/`ida_loaders` entry points.

`plugin relink` re-discovers `ida_plugins` and `ida_loaders` entry points from installed packages and recreates their symlinks. Use this after manually removing a symlink or after upgrading a package outside of `ida-setup`. Pass a package name to relink only that package's entry points.

```bash
ida-setup plugin list
ida-setup plugin uninstall keypatch
ida-setup plugin relink
ida-setup plugin relink keypatch
```

## Comparison with hcli

| Aspect | ida-setup plugin install | hcli |
|---|---|---|
| Metadata format | `pyproject.toml` (standard) | `ida-plugin.json` (custom) |
| Package source | any pip-compatible source | hex-rays plugin repository |
| Dependency management | pip/uv (standard) | custom |
| Versioning | PyPI/semver conventions | custom |
| Plugin discovery | Python entry points | centralized registry |
| Existing ecosystem | works with existing Python packages | requires new metadata |
