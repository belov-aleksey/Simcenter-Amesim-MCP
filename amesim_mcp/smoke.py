"""End-to-end test through the registered Codex STDIO MCP configuration."""
import argparse
import asyncio
from datetime import datetime
import json
import math
import os
from pathlib import Path
import tomllib
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .amesim_api import STATE


async def smoke(output=None):
    config_path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))["mcp_servers"]["amesim"]
    output = Path(output) if output else STATE / "smoke-tests" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True, exist_ok=False)
    parameters = StdioServerParameters(command=config["command"], args=config.get("args", []),
                                       env={**os.environ, **config.get("env", {})})
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            by_name = {tool.name: tool for tool in tools}
            if config.get("env", {}).get("AMESIM_MCP_ENABLE_EXECUTE_PYTHON") != "1":
                assert "execute_python" not in by_name
            assert by_name["remove_component"].annotations.destructiveHint
            assert by_name["status"].annotations.readOnlyHint

            async def call(tool_name, **arguments):
                print(tool_name, flush=True)
                result = await session.call_tool(tool_name, arguments)
                if result.isError:
                    raise RuntimeError(str(result.content))
                text = "\n".join(item.text for item in result.content if item.type == "text")
                try:
                    return json.loads(text)
                except ValueError:
                    return text

            try:
                connection = await call("connect")
                await call("create_circuit", name=str(output / "mass_spring_damper"))
                components = [
                    ("signal01", "source", "SIN0", "libsig", 0, 0),
                    ("forcecon", "force", "FORC", "libmec", 150, 0),
                    ("mass_friction_endstops", "mass", "MECMAS21", "libmec", 250, 0),
                    ("springdamper01", "spring", "SD0000", "libmec", 350, 0),
                    ("zerospeedsource", "ground", "V001", "libmec", 450, 0)]
                for icon, alias, submodel, library, x, y in components:
                    await call("add_component", icon_name=icon, alias=alias, x=x, y=y)
                    await call("change_submodel", alias=alias, submodel_name=submodel,
                               submodel_path="$AME/" + library + "/submodels")

                # Turn the two vertical icons before drawing any lines: moving an
                # already-connected icon does not move its line geometry in Amesim.
                for alias in ("force", "spring"):
                    await call("rotate_component", alias=alias, quarter_turns=1)

                async def geometry(alias):
                    return (await call("get_component_geometry", alias=alias))["geometry"]

                target_y = 90
                positions = {"source": 20, "force": 180, "mass": 320,
                             "spring": 470, "ground": 670}
                connected_port = {"source": 0, "force": 0, "mass": 1,
                                  "spring": 0, "ground": 0}
                for alias, target_x in positions.items():
                    top_left, _, ports = await geometry(alias)
                    desired_y = target_y + (50 if alias == "ground" else 0)
                    await call("move_component", alias=alias, x=target_x,
                               y=top_left[1] + desired_y - ports[connected_port[alias]][1])

                port_positions = {alias: (await geometry(alias))[2] for alias in positions}
                assert all(port_positions[alias][connected_port[alias]][1] == target_y
                           for alias in ("source", "force", "mass", "spring"))
                assert port_positions["ground"][0][1] == target_y + 50
                assert port_positions["force"][0][0] < port_positions["force"][1][0]
                assert port_positions["spring"][0][0] < port_positions["spring"][1][0]
                assert port_positions["mass"][1][0] < port_positions["mass"][0][0]
                assert all(port_positions[a][p][0] < port_positions[b][q][0]
                           for a, p, b, q in (("source", 0, "force", 0),
                                              ("force", 1, "mass", 1),
                                              ("mass", 0, "spring", 0),
                                              ("spring", 1, "ground", 0)))
                for a, p, b, q in [("source", 0, "force", 0), ("force", 1, "mass", 1),
                                    ("mass", 0, "spring", 0), ("spring", 1, "ground", 0)]:
                    route = ({"bend_points": [[port_positions["ground"][0][0], target_y]]}
                             if b == "ground" else {})
                    await call("connect_two_ports", alias1=a, port1=p, alias2=b, port2=q,
                               line_alias=a + "_to_" + b, **route)
                    line = await call("get_line_geometry", line_alias=a + "_to_" + b)
                    assert len(line["geometry"]) >= 2, line
                for path, value in [("mass@mass", "10"), ("srate@spring", "1000"), ("cdamp@spring", "20"),
                                    ("a@source", "100"), ("f@source", "1")]:
                    await call("set_parameter_value", data_path=path, value=value)
                await call("generate_code")
                for name, value in [("start_time_s", "0"), ("stop_time_s", "5"), ("interval_s", "0.01")]:
                    await call("set_run_parameter", name=name, value=value)
                await call("run_simulation")
                for path in ("x1@mass", "v1@mass"):
                    values = await call("get_variable_values", data_path=path)
                    assert len(values) >= 100
                    assert all(math.isfinite(v) for pair in values for v in pair)
                    assert all(a[0] < b[0] for a, b in zip(values, values[1:]))
                    assert abs(values[-1][0] - 5) < 1e-6
                    assert max(abs(pair[1]) for pair in values) > 1e-8
                    assert max(abs(pair[1]) for pair in values) < (1 if path.startswith("x1") else 10)
                exported = await call("export_results_csv", data_paths=["x1@mass", "v1@mass"],
                                      output_path=str(output / "results.csv"))
                await call("save_circuit_as", path=str(output / "saved_mass_spring_damper.ame"))
                await call("save_circuit")
                await call("close_circuit", save=True)
                assert (output / "saved_mass_spring_damper.ame").is_file()
                reopened = await call("open_ame_file", path=str(output / "saved_mass_spring_damper.ame"), fresh=True)
                assert reopened["isolated"] and reopened["opened"] != reopened["source"]
                saved_components = {alias: await geometry(alias) for alias in positions}
                saved_lines = {}
                for a, b in (("source", "force"), ("force", "mass"), ("mass", "spring"), ("spring", "ground")):
                    line = await call("get_line_geometry", line_alias=a + "_to_" + b)
                    assert len(line["geometry"]) >= 2, line
                    saved_lines[a + "_to_" + b] = line["geometry"]
                assert all(saved_components[alias][2][connected_port[alias]][1] == target_y
                           for alias in ("source", "force", "mass", "spring"))
                assert saved_components["ground"][2][0][1] == target_y + 50
                assert [saved_components["ground"][2][0][0], target_y] in saved_lines["spring_to_ground"]
                await call("generate_code")
                await call("run_simulation")
                reopened_values = await call("get_variable_values", data_path="v1@mass")
                assert len(reopened_values) >= 100 and abs(reopened_values[-1][0] - 5) < 1e-6
                await call("close_circuit", save=False)
                summary = {"passed": True, "connection": connection, "export": exported,
                           "output": str(output), "layout": {"components": saved_components,
                                                           "lines": saved_lines}}
            finally:
                await call("disconnect")
                assert "Not connected" in await call("status")
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    asyncio.run(smoke(args.output))


if __name__ == "__main__":
    main()
