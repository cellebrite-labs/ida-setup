# ida-setup

IDA Pro Python environment toolkit for macOS:

- venv setup (UI IDA + headless idalib)
- Python package management in that venv
- plugin/loader management
- stale-config detection and fixes

AI agent integration: `skills/ida-setup/SKILL.md`.

## Prerequisites

- macOS (only platform supported)
- IDA Pro >= 9.0
- Python 3.12+, framework-enabled, managed via [pyenv](https://github.com/pyenv/pyenv)
- [uv](https://github.com/astral-sh/uv)

Python must be built as a framework for `idapyswitch` to work.

## Why pyenv

`ida-setup` needs a Python whose path and version won't move under it.

- System Python: outdated, Apple-managed, can't pin a version.
- Homebrew Python: path and version can shift on upgrade, even via unrelated formulae. It serves Homebrew's own needs, not yours.
- pyenv: a stable, user-owned path with a version you pin explicitly.

So `ida-setup` targets pyenv Python. Everything else is untested.

## Setting up pyenv Python

- install pyenv
```bash
brew install pyenv
```

- install specific Python 3.12.x patch release (choose from `pyenv install --list | grep " 3.12"`)
  - `--enable-framework` is important for `idapyswitch` to work
```bash
PYTHON_CONFIGURE_OPTS="--enable-framework" pyenv install 3.12.x
```

- select the installed version and check that `pyenv which python` resolves to it
```bash
pyenv global 3.12.x
pyenv which python
```

## Installation

```bash
git clone https://github.com/cellebrite-labs/ida-setup.git
cd ida-setup
uv tool install -e .
```

## Quick start

```bash
# First time setup (--yes skips the confirmation prompt)
# - create venv (`~/.idapro/venv`)
# - point `idapyswitch` to the venv Python
# - install `idapro` and activate `idalib` for headless work
# - make IDA use the venv via LaunchAgent plist
ida-setup venv --yes --python "$(pyenv which python)"

# Check status
ida-setup status

# Refresh after IDA upgrade or fix inconsistencies
ida-setup venv

# Install packages into IDA's venv
ida-setup pip install foo bar

# Link a plugin file into ~/.idapro/plugins
ida-setup plugin link /path/to/plugin.py
```

## Flags

`--ida` and `--python` are used by most commands.

- `--ida`: which IDA installation to use. Default: newest `IDA Professional*.app` via Spotlight. Use `--ida /path/to/IDA.app` to pin a specific one.
- `--python`: interpreter for `pip`, `python`, and `plugin install`/`relink`:
  - Omit: reads `IDAPYTHON_VENV_EXECUTABLE` as configured by LaunchAgent (default `~/.idapro/venv`). This is what you want after first setup.
  - `--python ida`: launch IDA, probe its runtime, use that interpreter. Slow: launches IDA each time.
  - `--python /path/to/python3`: explicit path

## Commands

### venv

`~/.idapro/venv` is the Python environment used by both UI IDA and headless idalib, built from a pyenv framework Python. 
Creating or updating it does everything listed in Quick start. 
Idempotent: safe to re-run after IDA upgrades.

```bash
# First time: create venv from pyenv's framework Python
ida-setup venv --yes --python "$(pyenv which python)"

# After IDA upgrade: re-run to update `idapro`
ida-setup venv
```

### status

Show overall setup state: IDA, venv, LaunchAgent, idapro.

```bash
ida-setup status                                     # overview
ida-setup status --probe                             # + launch IDA, report its Python runtime
ida-setup status --probe --import foo --import bar   # + verify these packages import inside IDA
ida-setup --verbose status --probe                   # + debug logging, full probe JSON
```

### pip / python

Run pip or python using the selected interpreter.

```bash
ida-setup pip install foo                                             # shared venv (default)
ida-setup --python ida python -c 'import sys; print(sys.executable)'  # probe IDA's interpreter
ida-setup --python /path/to/python3 pip list                          # explicit interpreter
```

### plugin

Manage `~/.idapro/plugins` and `~/.idapro/loaders`.

#### list

```bash
ida-setup plugin list   # both plugins/ and loaders/
```

#### link / unlink

Symlink a plugin or loader file directly.

```bash
ida-setup plugin link /path/to/plugin.py             # symlink to ~/.idapro/plugins
ida-setup plugin link /path/to/loader.py --loader    # symlink to ~/.idapro/loaders
ida-setup plugin unlink plugin.py                    # removes from ~/.idapro/plugins
ida-setup plugin unlink loader.py --loader           # removes from ~/.idapro/loaders
```

`--force` allows overwriting existing symlinks or deleting real files and directories.

#### install / uninstall / relink

IDA plugins are IDAPython files. 
Usually you install the dependencies manually and link the plugin file. 
You can also declare dependencies and an `ida_plugins`/`ida_loaders` entry point in a `pyproject.toml`. 
`install` then manages both for you (see Plugin packaging below):

```bash
ida-setup plugin install keypatch              # install + symlink entry points
ida-setup plugin install -e /path/to/keypatch  # editable/local install
ida-setup plugin uninstall keypatch            # uninstall + remove entry point symlinks
ida-setup plugin relink                        # recreate symlinks for all packages
ida-setup plugin relink keypatch               # recreate symlinks for one package
```

## Plugin packaging

`plugin install` uses standard Python packaging (`pyproject.toml`) instead of a custom metadata format. 
Two entry point groups are recognized: `ida_plugins` and `ida_loaders`:

```toml
[project.entry-points."ida_plugins"]
keypatch = "keypatch.keypatch"
```

The tool installs the package and its dependencies into the venv via `uv pip`. 
It then symlinks each entry point's source `.py` file into `~/.idapro/plugins` or `~/.idapro/loaders`. 
Any source pip supports works: PyPI, git URLs, local paths.

For the full details (motivation, packaging guide, naming conventions, and comparison with hex-rays' `hcli`), see [docs/plugin-packaging.md](docs/plugin-packaging.md).

## Testing

```bash
uv run --group test pytest -q tests/
```
