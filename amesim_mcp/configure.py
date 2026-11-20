"""Update only the amesim TOML tables, preserving unrelated Codex settings."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib
from .amesim_api import discover_home


def configure(home=None, unsafe=False, force=False, config_path=None):
    if home:
        os.environ["AMESIM_HOME"] = home
    installation = discover_home()
    config = Path(config_path) if config_path else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    original = config.read_text(encoding="utf-8") if config.exists() else ""
    parsed = tomllib.loads(original)
    if "amesim" in parsed.get("mcp_servers", {}) and not force:
        raise FileExistsError("MCP amesim already exists. Use -Force to replace it.")
    # TOML sections end at the next table header. Quoted amesim headers are
    # rejected rather than edited ambiguously.
    if re.search(r'^\s*\[.*["\x27]amesim["\x27]', original, re.M):
        raise ValueError("Quoted amesim table header: edit configuration manually")
    sections = re.split(r'(?=^\s*\[[^\n]+\]\s*$)', original, flags=re.M)
    preserved = "".join(part for part in sections if not re.match(r'^\s*\[mcp_servers\.amesim(?:\.|\])', part))
    quote = lambda value: json.dumps(str(value))
    block = '\n[mcp_servers.amesim]\ncommand = ' + quote(sys.executable)
    block += '\nargs = ["-m", "amesim_mcp.server"]\nstartup_timeout_sec = 45\ntool_timeout_sec = 360\ndefault_tools_approval_mode = "auto"\n'
    block += '\n[mcp_servers.amesim.env]\nAMESIM_HOME = ' + quote(installation)
    block += '\nAMESIM_VERSION = "2404"\nAMESIM_MCP_ENABLE_EXECUTE_PYTHON = ' + quote("1" if unsafe else "0") + '\n'
    for tool in ("remove_component", "remove_line", "save_circuit", "close_circuit", "execute_python"):
        block += '\n[mcp_servers.amesim.tools.' + tool + ']\napproval_mode = "prompt"\n'
    updated = preserved.rstrip() + '\n' + block
    result = tomllib.loads(updated)
    remaining = dict(result.get("mcp_servers", {}))
    remaining.pop("amesim", None)
    prior = dict(parsed.get("mcp_servers", {}))
    prior.pop("amesim", None)
    assert remaining == prior, "Unrelated MCP settings changed"
    for key in parsed.keys() - {"mcp_servers"}:
        assert result[key] == parsed[key], "Unrelated Codex settings changed"
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        backup = config.with_name(config.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        shutil.copy2(config, backup)
        print("Backup:", backup)
    temporary = config.with_name(config.name + ".amesim.tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.replace(config)
    print("Configured amesim:", installation)
    print("Restart Codex to load the server.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home")
    parser.add_argument("--unsafe-python", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    configure(args.home, args.unsafe_python, args.force)


if __name__ == "__main__":
    main()
