# ida-setup

IDA Pro Python environment toolkit for macOS. Manage IDA's Python runtime: venv, idapyswitch, LaunchAgent, plugins.

`ida-setup` exists to make IDA setup easier on macOS. It creates a venv and points IDA at it, refreshes `idapyswitch`, `idapro`, and `idalib` after IDA upgrades, and installs or removes packages and plugins.

For AI agent integration: `skills/ida-setup/SKILL.md`.

## Prerequisites

- macOS (only platform supported)
- IDA Pro >= 9.0
- [pyenv](https://github.com/pyenv/pyenv) with a framework-enabled Python 3.12+
- [uv](https://github.com/astral-sh/uv)

Python must be built as a framework for `idapyswitch` to work.

## Why pyenv

We need a Python whose location and version stay under our control.

- System python: outdated, Apple-managed, and you can't pin a version.
- Homebrew python: location and version move on upgrade, including via unrelated formulae.
- pyenv: a stable user-owned path and an exact pinned patch release that changes only when you change it.

So `ida-setup` supports and tests pyenv, everything else is untested.

## Setting up pyenv Python

If you do not have pyenv, install it first:

```bash
brew install pyenv
```

Then install a concrete Python 3.12+ patch release. Replace `3.12.x` with a version from `pyenv install --list`.
`--enable-framework` is what makes it the framework build `idapyswitch` requires.

```bash
PYTHON_CONFIGURE_OPTS="--enable-framework" pyenv install 3.12.x
```

Then select it so `pyenv which python` resolves to this build:

```bash
pyenv global 3.12.x
```

## Installation

```bash
git clone https://github.com/cellebrite-labs/ida-setup.git
cd ida-setup
uv tool install -e .
```

## Quick start

```bash
# Create venv — runs idapyswitch, installs idapro, activates idalib, sets up LaunchAgent.
ida-setup venv --yes --python "$(pyenv which python)"

# Install packages into IDA's venv
ida-setup pip install foo bar
```

## Key concepts

`--ida` (IDA selection) — Most commands need an IDA installation. Default: newest `IDA Professional*.app` via Spotlight. Use `--ida /path/to/IDA.app` to pin a specific one.

`--python` — `pip`, `python`, and `plugin install/relink` commands need an interpreter:
  - Omit `--python` — reads `IDAPYTHON_VENV_EXECUTABLE` as configured by LaunchAgent (default `~/.idapro/venv`).
  - `--python ida` — launch IDA, probe its runtime, use that interpreter. Slow: launches IDA each time.
  - `--python /path/to/python3` — explicit path

venv — `~/.idapro/venv` is the Python environment IDA uses. The supported setup is pyenv framework Python. `idapro` is installed/upgraded and IDA's `idapyswitch` setting is refreshed each time you run `ida-setup venv`.

## Commands

### status

Show overall setup state (IDA, venv, LaunchAgent, idapro).
`ida-setup status`

With `--probe`, launches IDA and reports its Python runtime. Use `--import` to verify package visibility:

```bash
ida-setup status --probe
ida-setup --verbose status --probe
ida-setup status --probe --import foo --import bar
```

### venv

Create or update `~/.idapro/venv`. Installs/upgrades `idapro`, activates idalib, runs `idapyswitch` and sets up LaunchAgent. Idempotent — safe to re-run after IDA upgrades.

```bash
# First time: create venv from pyenv's framework Python
ida-setup venv --python "$(pyenv which python)"

# After IDA upgrade: re-run to update idapro
ida-setup venv
```

### pip / python

Run pip or python using the selected interpreter.

```bash
ida-setup pip install foo
ida-setup --python ida python -c 'import sys; print(sys.executable)'
ida-setup --python /path/to/python3 pip list
```

### plugin

Manage `~/.idapro/plugins` and `~/.idapro/loaders`.

```bash
ida-setup plugin list                                    # shows both plugins/ and loaders/
ida-setup plugin link /path/to/plugin.py                   # -> ~/.idapro/plugins
ida-setup plugin link /path/to/loader.py --loader           # -> ~/.idapro/loaders
ida-setup plugin unlink plugin.py
ida-setup plugin unlink loader.py --loader
```

Install a package that declares `ida_plugins` or `ida_loaders` entry points in its `pyproject.toml`. Installs the package via `uv pip install` and symlinks the entry point modules into `~/.idapro/plugins` and `~/.idapro/loaders`.

```bash
ida-setup plugin install keypatch
ida-setup plugin install -e /path/to/keypatch
```

Uninstall a package and remove its `ida_plugins`/`ida_loaders` entry points:

```bash
ida-setup plugin uninstall keypatch
```

Recreate entry point symlinks (e.g. after manually removing one):

```bash
ida-setup plugin relink          # all packages
ida-setup plugin relink keypatch # one package
```

## Plugin packaging

`plugin install` uses standard Python packaging instead of custom metadata formats. A plugin is a normal Python package that declares `ida_plugins` or `ida_loaders` entry points in `pyproject.toml`:

```toml
[project.entry-points."ida_plugins"]
keypatch = "keypatch.keypatch"
```

The tool installs the package via `uv pip install` and symlinks the entry point modules into `~/.idapro/plugins` (or `loaders`). Any source pip supports works: PyPI, git URLs, local paths.

For the full details — motivation, packaging guide, naming conventions, and comparison with hex-rays' `hcli` — see [docs/plugin-packaging.md](docs/plugin-packaging.md).

## Key options

- `--yes` — skip prompts; required for non-interactive runs
- `--verbose` — debug logging; with `status --probe` also prints full probe JSON
- `--force` (on `plugin link`/`plugin unlink`) — allow overwriting existing symlinks or deleting real files and directories

## Testing

```bash
uv run --group test pytest -q tests/
```
