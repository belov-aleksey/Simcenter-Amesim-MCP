"""Restricted JSON RPC bridge; Amesim calls stay on the process main thread."""
import contextlib
import hmac
import hashlib
import io
import json
import os
import sys
import threading
import ctypes
import ame_apy
import amesim
import rpyc
from rpyc.utils.server import OneShotServer

ALLOWED = set("""AMEGetAPIVersion AMECreateCircuit AMEOpenAmeFile AMESaveCircuit AMESaveCircuitAs AMECloseCircuit
AMEAddComponent AMEMoveComponent AMERotateComponent AMEFlipComponent AMERemoveComponent
AMEConnectTwoPorts AMEConnectTwoPortsWithLine AMERemoveLine AMECreateSupercomponent AMEChangeSubmodel AMEGetParameterValue
AMESetParameterValue AMEGetParameterInfos AMEGenerateCode AMESetRunParameter AMERunSimulation
AMEGetVariableValues AMEGetVariableInfos AMEGetLineGeometry AMEGetComponentGeometry
AMEGetComponentIconTransformation""".split())
TOKEN = os.environ.pop("AMESIM_MCP_TOKEN")
INITIALIZED = False
NAMESPACE = {"ame_apy": ame_apy, "amesim": amesim}


def watch_owner():
    """Release the worker even if the MCP process is killed without cleanup."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, int(os.environ["AMESIM_MCP_OWNER_PID"]))
    if not handle:
        os._exit(125)
    try:
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
    finally:
        kernel.CloseHandle(handle)
    os._exit(125)


def close_api():
    global INITIALIZED
    if INITIALIZED:
        try:
            ame_apy.AMECloseAPI()
        finally:
            INITIALIZED = False


class LimitedBuffer(io.StringIO):
    def write(self, value):
        if self.tell() + len(value) > 65536:
            raise RuntimeError("Python output exceeds 65536 characters")
        return super().write(value)


class AmesimService(rpyc.Service):
    def exposed_request(self, token, message):
        global INITIALIZED
        if not isinstance(token, str) or not hmac.compare_digest(token, TOKEN):
            raise PermissionError("Invalid worker session")
        try:
            req = json.loads(message)
            op = req["operation"]
            value = None
            if op == "identity":
                value = {"pid": os.getpid(), "proof": hmac.new(TOKEN.encode(), req["challenge"].encode(), hashlib.sha256).hexdigest()}
            elif op == "init":
                ame_apy.AMEInitAPI(False)
                INITIALIZED = True
            elif op == "close":
                close_api()
            elif op == "help":
                name = req["name"]
                if not name.startswith("AME") or not hasattr(ame_apy, name):
                    raise ValueError("Unknown Amesim API function")
                value = getattr(ame_apy, name).__doc__
            elif op == "call":
                if not INITIALIZED:
                    raise RuntimeError("API not initialized")
                if req["name"] not in ALLOWED:
                    raise PermissionError("Function is not in worker allowlist")
                args = req.get("args", [])
                if req["name"] == "AMEAddComponent":
                    args[2] = tuple(args[2])
                elif req["name"] == "AMEMoveComponent":
                    args[1] = tuple(args[1])
                elif req["name"] == "AMECreateSupercomponent":
                    args[0] = tuple(args[0])
                elif req["name"] == "AMEConnectTwoPortsWithLine" and len(args) == 6:
                    args[5] = tuple(tuple(point) for point in args[5])
                value = getattr(ame_apy, req["name"])(*args, **req.get("kwargs", {}))
            elif op == "execute" and os.environ.get("AMESIM_MCP_ENABLE_EXECUTE_PYTHON") == "1":
                timer = threading.Timer(30, lambda: os._exit(124))
                timer.daemon = True
                timer.start()
                try:
                    buf = LimitedBuffer()
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        exec(compile(req["code"], "<mcp>", "exec"), NAMESPACE)
                    value = buf.getvalue()
                finally:
                    timer.cancel()
            else:
                raise PermissionError("Unsupported operation")
            return json.dumps({"ok": True, "value": value})
        except Exception as exc:
            return json.dumps({"ok": False, "error": type(exc).__name__ + ": " + str(exc)})

    def on_disconnect(self, conn):
        close_api()


if __name__ == "__main__":
    threading.Thread(target=watch_owner, daemon=True).start()
    server = OneShotServer(AmesimService, hostname="127.0.0.1", port=0,
        protocol_config={"allow_pickle": False, "allow_public_attrs": False, "allow_all_attrs": False})
    ready = sys.argv[1]
    with open(ready + ".tmp", "w") as stream:
        json.dump({"port": server.port}, stream)
    os.replace(ready + ".tmp", ready)
    try:
        server.start()
    finally:
        close_api()
