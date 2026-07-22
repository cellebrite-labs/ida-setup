# Changelog

## [Unreleased]

## [0.4.1] - 2026-07-22

### Fixed
- Fixed `status` always reporting a stale `ida-config.json` on IDA >= 9.4, whose `py-activate-idalib.py` now stores the `.app` bundle path instead of the `Contents/MacOS` binaries path; `ida-setup` now handles both formats.
- Fixed `plugin install --help` printing a spurious "no new entry points found" message instead of just showing help.

### Changed
- Non-interactive `venv` without `--yes` now aborts instead of silently skipping LaunchAgent setup.
- idalib activation no longer passes an explicit install directory; it relies on `py-activate-idalib.py`'s self-detection instead.

### Removed
- Removed the stale `~/.idapro/idalib-venv` detection from `ida-setup status` (the legacy idalib-venv workflow was retired long ago).

## [0.4.0] - 2026-06-23

### Added
- `plugin uninstall <pkg>...` removes packages and their `ida_plugins`/`ida_loaders` entry-point symlinks.
- `plugin relink <pkg>` accepts a package filter to relink a single distribution instead of all.

### Changed
- `plugin list` distinguishes loadable entries from ignored filenames, flags missing managed entry points, and shows broken symlink targets.

### Fixed
- Run plugin entry-point discovery in isolated mode (`python -I`) so the user's site/env customizations can't interfere.

## [0.3.2] - 2026-05-21

### Added
- ANSI colored output across all CLI commands (respects `NO_COLOR` and non-TTY).

## [0.3.1] - 2026-05-13

### Added
- `plugin list` tags entry-point-managed symlinks with their package name (e.g. `[keypatch]`).
- Plugin packaging guide: `docs/plugin-packaging.md`.

## [0.3.0] - 2026-05-07

### Added
- `ida-setup venv` now runs `idapyswitch` automatically.

## [0.2.0] - 2026-05-05

### Breaking changes
- Rename the distribution package from `ida-setup` to `labs-ida-setup`; the CLI remains `ida-setup`.
- Rename `ida-setup plugins` to `ida-setup plugin`.
- Replace `ida-setup probe-ida` with `ida-setup status --probe`; `--import` is now available only with `status --probe`.
- Replace venv/idalib setup subcommands with `ida-setup venv`:
  - `ida-setup venv create --python ...` -> `ida-setup venv --python ...`
  - `ida-setup venv launchagent` -> `ida-setup venv`
  - `ida-setup idalib init` -> `ida-setup venv`
- Remove `venv status`, `idalib status`, and the standalone `idalib` command. Use `ida-setup status` instead.
- Remove `venv launchagent --venv <path>`; LaunchAgent setup now uses the shared `~/.idapro/venv`.
- Change plugin link/unlink syntax to positional arguments:
  - `ida-setup plugins link --source PATH` -> `ida-setup plugin link PATH`
  - `ida-setup plugins unlink --name NAME` -> `ida-setup plugin unlink NAME`
- Move `--force` from a global option to `plugin link` and `plugin unlink`.

### Added
- Add `plugin install <pip args>` to install a package with `uv pip install` and symlink new or changed `ida_plugins` / `ida_loaders` entry points into IDA.
- Add `plugin relink` to recreate all discovered `ida_plugins` / `ida_loaders` entry point symlinks.
- Add loader support:
  - `plugin list` now shows both `~/.idapro/plugins` and `~/.idapro/loaders`.
  - `plugin link/unlink --loader` targets `~/.idapro/loaders`.

### Changed
- `ida-setup venv` is now idempotent: it creates the venv if missing, otherwise updates `idapro`, activates idalib, verifies `import idapro`, and sets up the LaunchAgent.
- Switch venv creation and package installation to `uv`; `uv` is now required on `PATH`.
- For passthrough commands, ida-setup options must appear before the command. Arguments after `pip`, `python`, or `plugin install` are forwarded to the underlying tool.
- `plugin link` no longer prompts before overwriting; replacing an existing different symlink or real file/directory requires `--force`.
- `plugin unlink` removes symlinks without prompting; deleting real files/directories requires `--force`.
- Skip the LaunchAgent prompt when the installed LaunchAgent is already up to date.
- Derive package versions from git tags via `setuptools-scm`.

### Fixed
- Preserve pip-style flags such as `-e` and `--verbose` when parsing `plugin install` arguments.
- Refuse to replace real files/directories when creating entry-point symlinks.

## [0.1.2] - 2026-04-20

### Changed
- Consolidated UI IDA and idalib onto the shared venv at `~/.idapro/venv`; `venv create` now installed `idapro` and activated idalib, and `idalib init` now operated on the shared venv instead of creating `~/.idapro/idalib-venv`.
- `ida-setup status` now reported when IDA's `idapyswitch` Python selection did not match the venv Python and printed the matching `idapyswitch` path.

### Fixed
- `--python ida` now failed fast when IDA was not using a venv, instead of treating the IDA app binary as a Python interpreter.
- `venv create` and `idalib init` now required an explicit `--python /path/to/python3`, preventing silent misconfiguration from probing IDA's embedded interpreter.
- `idalib init` now installed `idapro` from the bundled wheel on IDA 9.3 and newer.
- `ida-setup status` now distinguished a broken legacy `~/.idapro/idalib-venv` from a missing one and flagged stale `ida-config.json` entries for a different IDA installation.

## [0.1.1] - 2026-02-12

Add versioning and changelog.

## [0.1.0] - 2026-02-12

Initial versioned release.
