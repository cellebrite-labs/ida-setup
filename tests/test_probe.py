"""Tests for _probe module: probe script generation."""

from pathlib import Path

from ida_setup._probe import write_probe_script


class TestWriteProbeScript:
    def test_generates_valid_python(self, tmp_path: Path) -> None:
        script = tmp_path / "probe.py"
        out_json = tmp_path / "out.json"
        write_probe_script(script_path=script, out_json=out_json, import_names=["pydantic"])

        content = script.read_text()
        # Should be valid Python syntax.
        compile(content, str(script), "exec")

    def test_contains_import_names(self, tmp_path: Path) -> None:
        script = tmp_path / "probe.py"
        out_json = tmp_path / "out.json"
        write_probe_script(script_path=script, out_json=out_json, import_names=["requests", "pydantic"])

        content = script.read_text()
        assert '"requests"' in content
        assert '"pydantic"' in content

    def test_contains_output_path(self, tmp_path: Path) -> None:
        script = tmp_path / "probe.py"
        out_json = tmp_path / "out.json"
        write_probe_script(script_path=script, out_json=out_json, import_names=[])

        content = script.read_text()
        assert str(out_json) in content

    def test_empty_imports(self, tmp_path: Path) -> None:
        script = tmp_path / "probe.py"
        out_json = tmp_path / "out.json"
        write_probe_script(script_path=script, out_json=out_json, import_names=[])

        content = script.read_text()
        compile(content, str(script), "exec")
        assert "IMPORTS = []" in content
