"""Tests for IDA registry parsing and ida-config.json."""

import json
from pathlib import Path

from ida_setup._ida import IdaApp, read_ida_config_install_dir, read_python3_target_dll


def _make_ida_reg(value: str) -> bytes:
    """Build a minimal ida.reg with a Python3TargetDLL entry."""
    key = b"Python3TargetDLL\x00"
    raw = value.encode("utf-8")
    return key + len(raw).to_bytes(4, "little") + b"\x01" + raw


class TestReadPython3TargetDLL:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert read_python3_target_dll(tmp_path / "missing.reg") is None

    def test_parses_value(self, tmp_path: Path) -> None:
        reg = tmp_path / "ida.reg"
        path = "/opt/homebrew/Cellar/python@3.12/3.12.12_2/Frameworks/Python.framework/Versions/3.12/Python"
        reg.write_bytes(_make_ida_reg(path))
        assert read_python3_target_dll(reg) == path

    def test_wrong_type_byte(self, tmp_path: Path) -> None:
        reg = tmp_path / "ida.reg"
        key = b"Python3TargetDLL\x00"
        raw = b"/some/path"
        reg.write_bytes(key + len(raw).to_bytes(4, "little") + b"\x02" + raw)
        assert read_python3_target_dll(reg) is None

    def test_no_key(self, tmp_path: Path) -> None:
        reg = tmp_path / "ida.reg"
        reg.write_bytes(b"SomeOtherKey\x00\x04\x00\x00\x00\x01test")
        assert read_python3_target_dll(reg) is None


class TestReadIdaConfigInstallDir:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert read_ida_config_install_dir(tmp_path / "missing.json") is None

    def test_reads_install_dir(self, tmp_path: Path) -> None:
        cfg = tmp_path / "ida-config.json"
        cfg.write_text(json.dumps({"Paths": {"ida-install-dir": "/opt/ida"}}))
        assert read_ida_config_install_dir(cfg) == Path("/opt/ida")

    def test_reads_install_dir_app_bundle(self, tmp_path: Path) -> None:
        """IDA >= 9.4 stores the .app bundle path directly."""
        cfg = tmp_path / "ida-config.json"
        val = "/Applications/IDA Professional 9.4.app"
        cfg.write_text(json.dumps({"Paths": {"ida-install-dir": val}}))
        assert read_ida_config_install_dir(cfg) == Path(val)

    def test_normalizes_legacy_bin_dir(self, tmp_path: Path) -> None:
        """IDA < 9.4 stores the literal Contents/MacOS bin dir."""
        cfg = tmp_path / "ida-config.json"
        val = "/Applications/IDA Professional 9.2.app/Contents/MacOS"
        cfg.write_text(json.dumps({"Paths": {"ida-install-dir": val}}))
        assert read_ida_config_install_dir(cfg) == Path("/Applications/IDA Professional 9.2.app")

    def test_missing_key(self, tmp_path: Path) -> None:
        cfg = tmp_path / "ida-config.json"
        cfg.write_text(json.dumps({"Paths": {}}))
        assert read_ida_config_install_dir(cfg) is None

    def test_invalid_json(self, tmp_path: Path) -> None:
        cfg = tmp_path / "ida-config.json"
        cfg.write_text("not json")
        assert read_ida_config_install_dir(cfg) is None

    def test_malformed_paths_value(self, tmp_path: Path) -> None:
        cfg = tmp_path / "ida-config.json"
        cfg.write_text(json.dumps({"Paths": None}))
        assert read_ida_config_install_dir(cfg) is None

    def test_malformed_install_dir_type(self, tmp_path: Path) -> None:
        cfg = tmp_path / "ida-config.json"
        cfg.write_text(json.dumps({"Paths": {"ida-install-dir": 123}}))
        assert read_ida_config_install_dir(cfg) is None


class TestIdaAppInstallDir:
    def test_install_dir_is_app_bundle(self) -> None:
        app = IdaApp(path=Path("/Applications/IDA Professional 9.3.app"), version=(9, 3))
        assert app.install_dir == Path("/Applications/IDA Professional 9.3.app")

    def test_bin_dir_macos(self) -> None:
        app = IdaApp(path=Path("/Applications/IDA Professional 9.3.app"), version=(9, 3))
        assert app.bin_dir == Path("/Applications/IDA Professional 9.3.app/Contents/MacOS")

    def test_idapyswitch_under_bin_dir(self) -> None:
        app = IdaApp(path=Path("/Applications/IDA Professional 9.3.app"), version=(9, 3))
        assert app.idapyswitch == app.bin_dir / "idapyswitch"
