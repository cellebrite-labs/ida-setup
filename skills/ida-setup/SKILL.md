---
name: ida-setup
description: cli to manage IDA Pro Python runtime, venv, LaunchAgent, and plugins.
---

# ida-setup

## Prerequisites

- macOS only.
- IDA Pro >= 9.0.
- pyenv with a framework-enabled Python 3.12+. Other Python distributions are untested and likely won't work.
- uv on PATH.

## Installation

`uv tool install -e /path/to/ida-setup`

If already installed, invoke as `ida-setup`. Always pass `--yes` when running from an agent.

## Commands

- `ida-setup status`: Show overall state.
- `ida-setup [--verbose] status --probe [--import <module>]`: Launch IDA and report its Python runtime.
- `ida-setup venv --python /path/to/python3`: Create or update `~/.idapro/venv`, install `idapro`, activate idalib, run `idapyswitch`, set up LaunchAgent. `--python` is required for initial creation (`"$(pyenv which python)"`). Re-run without `--python` after IDA upgrades.
- `ida-setup pip <args>`: Run pip using the selected interpreter.
- `ida-setup python <args>`: Run python using the selected interpreter.
- `ida-setup plugin list`: Show `~/.idapro/plugins` and `~/.idapro/loaders`.
- `ida-setup plugin link <path>... [--loader]`: Symlink into plugins (or loaders with `--loader`).
- `ida-setup plugin unlink <name>... [--loader] [--force]`: Remove symlink.
- `ida-setup plugin install <pip args>`: Install a package and symlink its `ida_plugins`/`ida_loaders` entry points. All args forwarded to `uv pip install`.
- `ida-setup plugin relink`: Recreate all entry point symlinks.

## Python selection

Commands that need an interpreter (`pip`, `python`, `plugin install`, `plugin relink`) use `--python`:

- Omitted: uses `IDAPYTHON_VENV_EXECUTABLE` env var (set by LaunchAgent), pointing into `~/.idapro/venv`. After setup use this one.
- `--python ida`: Launches IDA, probes its runtime. Slow. Requires IDA to use venv.
- `--python /path/to/python3`: Explicit path.

## IDA selection
Auto-detects newest IDA via Spotlight. Pin with `--ida /path/to/IDA.app`.

## Plugin packaging

To make a plugin installable via `ida-setup plugin install`, declare entry points in `pyproject.toml`:

```toml
[project.entry-points."ida_plugins"]
my_plugin = "my_package.plugin_module"

[project.entry-points."ida_loaders"]
my_loader = "my_package.loader_module"
```

Values are dotted module paths only - no `:callable` part. The module's `.py` file is symlinked into IDA's plugin/loader directory.
Install with `ida-setup plugin install <source>` (any `uv pip install` source works).

## Gotchas

- `--yes` is required when running from an agent (non-interactive).
- If the LaunchAgent env var is not visible after setup, the user may need to log out and back in.
