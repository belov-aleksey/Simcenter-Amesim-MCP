"""Opt-in license-consuming integration checks."""
import ctypes
import json
import os
import socket
import subprocess
import sys
import unittest
from amesim_mcp.amesim_api import AmesimConnection


@unittest.skipUnless(os.environ.get("AMESIM_MCP_LIVE_TESTS") == "1", "Set AMESIM_MCP_LIVE_TESTS=1 to use a real license")
class LiveTests(unittest.TestCase):
    def test_restricted_rpc_and_port_release(self):
        connection = AmesimConnection()
        try:
            connection.connect()
            port = connection._port
            self.assertIn("AMESaveCircuitAs", connection.request("help", name="AMESaveCircuitAs"))
            with self.assertRaises(RuntimeError):
                connection.request("call", name="AMEInitAPI")
            with self.assertRaises(RuntimeError):
                connection.request("execute", code="print('must not run')")
        finally:
            connection.disconnect()
        with socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)

    def test_worker_exits_after_owner_is_killed(self):
        code = (
            "from amesim_mcp.amesim_api import AmesimConnection; import json,time;"
            "c=AmesimConnection(); c.connect();"
            "print(json.dumps(c.request('identity',challenge='lifecycle-test')),flush=True);time.sleep(60)"
        )
        owner = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        handle = None
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        try:
            identity = json.loads(owner.stdout.readline())
            handle = kernel.OpenProcess(0x00100000, False, identity["pid"])
            self.assertTrue(handle)
            owner.terminate()
            owner.wait(timeout=10)
            self.assertEqual(kernel.WaitForSingleObject(handle, 10000), 0)
        finally:
            if owner.poll() is None:
                owner.terminate()
                owner.wait(timeout=10)
            owner.stdout.close()
            if handle:
                kernel.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
