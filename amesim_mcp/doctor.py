"""Installation and optional live license diagnostics."""
import argparse
import importlib.metadata
import json
import os
import platform
import sys
from .amesim_api import AmesimConnection, discover_home, registry_env


def diagnose(deep=False):
    checks = {"python": sys.version.split()[0], "executable": sys.executable,
              "python_ok": sys.version_info >= (3, 12), "architecture": platform.architecture()[0],
              "venv": sys.prefix != sys.base_prefix}
    checks["dependencies"] = {name: importlib.metadata.version(name) for name in ("mcp", "rpyc")}
    checks["license_environment_present"] = {
        name: bool(os.environ.get(name) or registry_env(name))
        for name in ("LMS_LICENSE", "SC1D_LICENSING_TYPE")}
    try:
        home = discover_home()
        checks.update(amesim_home=str(home), amepython=(home / "win64/AMEPython.exe").is_file(),
                      circuit_checker=(home / "win64/AMECirChecker.exe").is_file())
        checks["ok"] = checks["python_ok"] and checks["amepython"] and checks["circuit_checker"]
        if deep:
            connection = AmesimConnection()
            try:
                checks["connection"] = connection.connect()
            finally:
                connection.disconnect()
            checks["worker_stopped"] = connection._worker_proc is None
    except Exception as exc:
        checks.update(ok=False, error=str(exc))
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()
    result = diagnose(args.deep)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
