"""Owned, authenticated Amesim worker connection."""
import atexit
import json
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import subprocess
import time
import threading
from functools import wraps
import winreg
import rpyc

DEFAULT_VERSION = "2404"
ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "amesim-mcp"


def synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


def registry_env(name):
    for hive, key in [(winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")]:
        try:
            with winreg.OpenKey(hive, key) as handle:
                return winreg.QueryValueEx(handle, name)[0]
        except OSError:
            pass
    return None


def discover_home(version=DEFAULT_VERSION):
    explicit = os.environ.get("AMESIM_HOME")
    candidates = [Path(explicit)] if explicit else []
    if not explicit:
        if os.environ.get("AME"):
            candidates.append(Path(os.environ["AME"]))
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for base in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    with winreg.OpenKey(hive, base) as root:
                        for i in range(winreg.QueryInfoKey(root)[0]):
                            try:
                                with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                                    name = winreg.QueryValueEx(key, "DisplayName")[0]
                                    if "Simcenter" in name and version in name:
                                        candidates.append(Path(winreg.QueryValueEx(key, "InstallLocation")[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        for drive in ("C:", "D:", "E:"):
            for folder in ("Program Files/Simcenter", "Program Files/Siemens/Simcenter", "Programs/Simcenter"):
                candidates.append(Path(drive + "/") / folder / version)
    for candidate in candidates:
        for home in (candidate, candidate / "Amesim"):
            if (home / "win64/AMEPython.exe").is_file():
                return home.resolve()
    raise FileNotFoundError("Amesim " + version + " not found. Set AMESIM_HOME to the directory containing win64/AMEPython.exe.")


class ApiProxy:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        if not name.startswith("AME"):
            raise AttributeError(name)
        return lambda *args, **kwargs: self.connection.request("call", name=name, args=args, kwargs=kwargs)


class AmesimConnection:
    def __init__(self):
        self._lock = threading.RLock()
        self._conn = self._worker_proc = self._log = None
        self._version = self._port = None
        self._token = None
        atexit.register(self.disconnect)

    @property
    def api(self):
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return ApiProxy(self)

    @synchronized
    def request(self, operation, **payload):
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        try:
            result = json.loads(self._conn.root.request(self._token, json.dumps(dict(operation=operation, **payload))))
        except Exception:
            self._cleanup()
            raise RuntimeError("Worker communication failed or timed out; disconnected. See worker log.") from None
        if not result["ok"]:
            raise RuntimeError(result["error"])
        return result.get("value")

    @synchronized
    def connect(self, version=DEFAULT_VERSION):
        if self.is_connected():
            return {"connected": True, "version": self._version}
        home = discover_home(version)
        logs = STATE / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._token = secrets.token_hex(32)
        ready = logs / ("ready-" + secrets.token_hex(8) + ".json")
        self.log_path = logs / ("worker-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4) + ".log")
        env = os.environ.copy()
        env.update(AME=str(home), AMESIM_MCP_TOKEN=self._token, AMESIM_MCP_OWNER_PID=str(os.getpid()))
        for name in ("LMS_LICENSE", "SC1D_LICENSING_TYPE"):
            if not env.get(name) and registry_env(name):
                env[name] = registry_env(name)
        env["PATH"] = os.pathsep.join([str(home), str(home / "win64"), str(home / "win32"), env.get("PATH", "")])
        env["PYTHONPATH"] = str(ROOT / "vendor")
        self._log = self.log_path.open("w", encoding="utf-8")
        try:
            self._worker_proc = subprocess.Popen(
                [str(home / "win64/AMEPython.exe"), "-s", str(ROOT / "amesim_mcp/worker_entry.py"), str(ready)],
                env=env, cwd=str(STATE), stdin=subprocess.DEVNULL, stdout=self._log, stderr=self._log,
                creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 45
            while not ready.exists():
                if self._worker_proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Worker failed to start; inspect " + str(self.log_path))
                time.sleep(0.1)
            self._port = json.loads(ready.read_text())["port"]
            self._conn = rpyc.connect("127.0.0.1", self._port,
                config={"sync_request_timeout": 300, "allow_pickle": False})
            challenge = secrets.token_hex(32)
            identity = self.request("identity", challenge=challenge)
            proof = hmac.new(self._token.encode(), challenge.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(identity["proof"], proof):
                raise RuntimeError("Worker identity mismatch")
            self.request("init")
            api_version = self.api.AMEGetAPIVersion()
            if str(api_version[-1]) != version:
                raise RuntimeError("Requested Amesim " + version + " but installed API reports " + str(api_version))
            self._version = version
            return {"connected": True, "version": version, "api_version": api_version,
                    "port": self._port, "log": str(self.log_path)}
        except Exception:
            self.disconnect()
            raise
        finally:
            ready.unlink(missing_ok=True)

    def is_connected(self):
        return self._conn is not None and self._worker_proc is not None and self._worker_proc.poll() is None

    def _cleanup(self):
        conn, self._conn = self._conn, None
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if self._worker_proc:
            try:
                self._worker_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # AMEPython.exe launches a child interpreter: stop its owned tree.
                subprocess.run(["taskkill", "/PID", str(self._worker_proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                self._worker_proc.wait(timeout=5)
            self._worker_proc = None
        if self._log:
            self._log.close()
            self._log = None
        self._version = self._port = None

    @synchronized
    def disconnect(self):
        if self._conn:
            try:
                self.request("close")
            except Exception:
                pass
        self._cleanup()
        return "Disconnected; worker stopped."

    def execute_python(self, code):
        if os.environ.get("AMESIM_MCP_ENABLE_EXECUTE_PYTHON") != "1":
            raise PermissionError("execute_python is disabled")
        return self.request("execute", code=code)
