import asyncio
import importlib
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import Mock, patch
from amesim_mcp.amesim_api import AmesimConnection, discover_home
from amesim_mcp.configure import configure
from amesim_mcp.results import export


class SafetyTests(unittest.TestCase):
    def test_home_precedence(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "Amesim"
            (home / "win64").mkdir(parents=True)
            (home / "win64/AMEPython.exe").touch()
            with patch.dict(os.environ, {"AMESIM_HOME": str(home)}):
                self.assertEqual(discover_home(), home.resolve())
            with patch.dict(os.environ, {"AMESIM_HOME": str(home / "invalid")}):
                with self.assertRaises(FileNotFoundError):
                    discover_home()

    def test_config_preservation_and_force(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / "config.toml"
            config.write_text('model = "example"\n[mcp_servers.other]\ncommand = "other"\n', encoding="utf-8")
            with patch("amesim_mcp.configure.discover_home", return_value=Path(root)):
                configure(config_path=config)
                parsed = tomllib.loads(config.read_text())
                self.assertEqual(parsed["model"], "example")
                self.assertEqual(parsed["mcp_servers"]["other"]["command"], "other")
                self.assertEqual(parsed["mcp_servers"]["amesim"]["tools"]["save_circuit"]["approval_mode"], "prompt")
                with self.assertRaises(FileExistsError):
                    configure(config_path=config)
                configure(force=True, config_path=config)
                self.assertTrue(list(Path(root).glob("*.backup-*")))

    def test_export_protection(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "results.csv"
            connection = Mock()
            connection.api.AMEGetVariableValues.return_value = [[0, 1], [1, 2]]
            self.assertEqual(export(connection, ["x"], str(path))["samples"], 2)
            with self.assertRaises(FileExistsError):
                export(connection, ["x"], str(path))
            connection.api.AMEGetVariableValues.side_effect = [[[0, 1]], [[1, 2]]]
            with self.assertRaises(ValueError):
                export(connection, ["x", "v"], str(Path(root) / "different.csv"))

    def test_timeout_cleanup(self):
        connection = AmesimConnection()
        connection._conn = Mock()
        connection._conn.root.request.side_effect = TimeoutError()
        worker = connection._worker_proc = Mock()
        with self.assertRaises(RuntimeError):
            connection.request("identity")
        worker.wait.assert_called_once()
        self.assertIsNone(connection._conn)
        self.assertIsNone(connection._worker_proc)

    def test_tool_registration(self):
        import amesim_mcp.server as server
        for enabled in ("0", "1"):
            with patch.dict(os.environ, {"AMESIM_MCP_ENABLE_EXECUTE_PYTHON": enabled}):
                server = importlib.reload(server)
                tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
                self.assertEqual("execute_python" in tools, enabled == "1")
                for name in ("remove_component", "remove_line", "save_circuit", "close_circuit"):
                    self.assertTrue(tools[name].annotations.destructiveHint)
                self.assertTrue(tools["get_api_help"].annotations.readOnlyHint)
        with patch.dict(os.environ, {"AMESIM_MCP_ENABLE_EXECUTE_PYTHON": "0"}):
            importlib.reload(server)

    def test_save_as_protection(self):
        from amesim_mcp.server import save_circuit_as
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "existing.ame"
            path.write_text("original")
            with self.assertRaises(FileExistsError):
                save_circuit_as(str(path))
            self.assertEqual(path.read_text(), "original")

    def test_visible_connection_uses_line_api(self):
        from amesim_mcp.server import connect_two_ports
        with patch("amesim_mcp.server.ame") as connection:
            connect_two_ports("source", 0, "force", 0, "source_to_force")
            connection.api.AMEConnectTwoPortsWithLine.assert_called_once_with(
                "source", 0, "force", 0, "source_to_force")
            connection.api.AMEConnectTwoPorts.assert_not_called()

    def test_connection_accepts_bend_points(self):
        from amesim_mcp.server import connect_two_ports

        with patch("amesim_mcp.server.ame") as connection:
            connect_two_ports("spring", 1, "ground", 0, "spring_to_ground",
                              [[600, 90]])
            connection.api.AMEConnectTwoPortsWithLine.assert_called_once_with(
                "spring", 1, "ground", 0, "spring_to_ground", [[600, 90]])
            with self.assertRaises(ValueError):
                connect_two_ports("spring", 1, "ground", 0, "bad", [[600]])

    def test_component_geometry_is_read_only(self):
        from amesim_mcp.server import get_component_geometry

        with patch("amesim_mcp.server.ame") as connection:
            result = get_component_geometry("mass")
            self.assertEqual(result["alias"], "mass")
            connection.api.AMEGetComponentGeometry.assert_called_once_with("mass")

    def test_fresh_open_does_not_change_original_or_sidecars(self):
        from amesim_mcp.server import open_ame_file
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "model.ame"
            expanded = Path(root) / "model_.cir"
            source.write_bytes(b"archive")
            expanded.write_bytes(b"old expanded data")
            with patch("amesim_mcp.amesim_api.STATE", Path(root)), patch("amesim_mcp.server.ame") as connection:
                result = open_ame_file(str(source), fresh=True)
            self.assertTrue(result["isolated"])
            self.assertNotEqual(result["opened"], str(source))
            self.assertEqual(Path(result["opened"]).read_bytes(), b"archive")
            self.assertEqual(expanded.read_bytes(), b"old expanded data")
            connection.api.AMEOpenAmeFile.assert_called_once_with(result["opened"])


if __name__ == "__main__":
    unittest.main()
