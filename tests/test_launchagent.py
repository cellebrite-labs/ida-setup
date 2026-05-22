"""Tests for _launchagent module."""

from pathlib import Path
from unittest.mock import patch

from ida_setup._launchagent import is_launch_agent_up_to_date, render_env_plist


class TestRenderEnvPlist:
    def test_contains_label(self) -> None:
        result = render_env_plist(Path("/Users/test/.idapro/venv/bin/python3"))
        assert "com.cellebrite.ida-setup.env" in result

    def test_contains_venv_path(self) -> None:
        venv = Path("/Users/test/.idapro/venv/bin/python3")
        result = render_env_plist(venv)
        assert str(venv) in result

    def test_contains_env_var_name(self) -> None:
        result = render_env_plist(Path("/Users/test/.idapro/venv/bin/python3"))
        assert "IDAPYTHON_VENV_EXECUTABLE" in result

    def test_uses_direct_launchctl_program_arguments(self) -> None:
        result = render_env_plist(Path("/Users/test/.idapro/venv/bin/python3"))
        assert "<string>/bin/launchctl</string>" in result
        assert "<string>setenv</string>" in result
        assert "<string>-c</string>" not in result

    def test_valid_xml(self) -> None:
        import xml.etree.ElementTree as ET

        result = render_env_plist(Path("/Users/test/.idapro/venv/bin/python3"))
        # Should parse without error (strip the DOCTYPE which ET doesn't handle).
        lines = result.splitlines()
        xml_lines = [line for line in lines if not line.startswith("<!DOCTYPE")]
        ET.fromstring("\n".join(xml_lines))

    def test_deterministic(self) -> None:
        venv = Path("/Users/test/.idapro/venv/bin/python3")
        assert render_env_plist(venv) == render_env_plist(venv)


class TestIsLaunchAgentUpToDate:
    def test_up_to_date(self, tmp_path: Path) -> None:
        venv_python = Path("/Users/test/.idapro/venv/bin/python3")
        plist = tmp_path / "agent.plist"
        plist.write_text(render_env_plist(venv_python), encoding="utf-8")

        with patch("ida_setup._launchagent.PLIST_PATH", plist):
            assert is_launch_agent_up_to_date(venv_python) is True

    def test_different_python(self, tmp_path: Path) -> None:
        old_python = Path("/Users/test/.idapro/venv/bin/python3")
        new_python = Path("/Users/test/.idapro/venv2/bin/python3")
        plist = tmp_path / "agent.plist"
        plist.write_text(render_env_plist(old_python), encoding="utf-8")

        with patch("ida_setup._launchagent.PLIST_PATH", plist):
            assert is_launch_agent_up_to_date(new_python) is False

    def test_plist_missing(self, tmp_path: Path) -> None:
        with patch("ida_setup._launchagent.PLIST_PATH", tmp_path / "no-such.plist"):
            assert is_launch_agent_up_to_date(Path("/some/python")) is False
