---
name: ida-setup
description: "IDA Pro Python runtime setup: venv, idapyswitch, LaunchAgent, plugins."
---

# ida-setup

## Prerequisites

- macOS only.
- IDA Pro >= 9.0.
- pyenv-managed, framework-enabled Python 3.12+. Other Python sources are untested and likely won't work. If not set up, see this repo's README ("Setting up pyenv Python").
- uv on PATH.

## Commands

- `status`: show setup state.
- `venv`: create/update the shared venv.
- `pip` / `python`: run pip/python using the selected interpreter.
- `plugin`: manage plugins/loaders. Subcommands: `list`, `link`, `unlink`, `install`, `uninstall`, `relink` (see `plugin --help`).

## First-time setup

1. Check `which ida-setup`; if missing, `uv tool install -e <this repo>`.
2. Confirm a pyenv-managed, framework-enabled Python 3.12+ exists (`pyenv which python`); if not, see Prerequisites.
3. `ida-setup venv --yes --python "$(pyenv which python)"`: creates the venv, installs idapro, activates idalib, runs idapyswitch, and configures the LaunchAgent.

## Running commands

Always pass `--yes` on `venv`: without it, non-interactive runs may abort. Other commands don't prompt, so `--yes` there is harmless but unnecessary.

Re-run `venv` (omit `--python`) after an IDA upgrade to refresh idapyswitch, idalib, and the LaunchAgent.

`ida-setup --help` / `ida-setup <cmd> --help` are accurate and complete for flags and subcommands.

`pip`, `python`, and `plugin install` are raw passthroughs to the underlying tool: `--help` on those goes to `uv pip`/`python`, not ida-setup's own help.

## Plugin packaging

Single `.py` file with manually-installed dependencies: use `plugin link`. Repo with (or where you add) a `pyproject.toml` declaring entry points: use `plugin install`, which installs the package and its dependencies, then symlinks the entry point automatically.

To declare entry points in `pyproject.toml`:

```toml
[project.entry-points."ida_plugins"]
my_plugin = "my_package.plugin_module"

[project.entry-points."ida_loaders"]
my_loader = "my_package.loader_module"
```

Values are dotted module paths only, no `:callable` part. The module's `.py` file is symlinked into IDA's plugin/loader directory.

## Guardrails

- `plugin link`/`unlink --force` can overwrite or delete real files and directories, not just symlinks. Confirm with the user before using `--force` on anything that isn't clearly a stray symlink.

## Gotchas

- `venv --python <path>` is required only for the first creation.
- `venv` rejects `--python ida`: before a venv exists, IDA's embedded Python reports its own binary as `sys.executable`, so there's nothing valid to probe. Use an explicit path.
- After LaunchAgent setup, if `IDAPYTHON_VENV_EXECUTABLE` isn't visible yet, the user may need to log out and back in.
