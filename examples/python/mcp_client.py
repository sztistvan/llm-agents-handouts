"""A minimal MCP client over stdio (Module 10), written by hand (no SDK). Standard library only.

Shared building block. Layers: llm_client -> agent (the loop) -> mcp_client -> m10_* lessons.
`McpClient` starts a server as a subprocess, speaks JSON-RPC 2.0 (one message per line) and turns the server's tools into
`Tool` objects for `run_agent`, so an agent uses MCP tools exactly like local functions:

    with McpClient([sys.executable, "examples/python/m10_mcp_server.py"]) as client:
        run_agent("Save a note: buy milk", client.tools())

The handshake is the one of the 2025-11-25 revision (and earlier): `initialize`, then the notification
`notifications/initialized`. The newest revision (2026-07-28) removes it, see docs/10-tools-mcp.md.
"""
import json
import queue
import subprocess
import threading

from agent import Tool

PROTOCOL_VERSION = "2025-11-25"


class McpError(Exception):
    """A JSON-RPC error response (a protocol problem: unknown method or tool, bad request)."""

    def __init__(self, error: dict):
        super().__init__(f"{error.get('code')}: {error.get('message')}")
        self.code = error.get("code")


class McpClient:
    def __init__(self, command: list[str], env: dict | None = None, trace: bool = False, timeout: float = 30.0):
        self.trace, self.timeout, self._next_id = trace, timeout, 1
        self._proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)  # bytes, so that "\n" stays "\n" on Windows
        self._lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()  # a thread, so that a silent server cannot block us forever
        self.server_info: dict = {}

    def _read(self) -> None:
        for raw in self._proc.stdout:
            self._lines.put(raw.decode("utf-8").strip())
        self._lines.put(None)  # the server closed stdout

    def _send(self, message: dict) -> None:
        text = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if self.trace:
            print(f"   client -> server  {text[:200]}")
        self._proc.stdin.write((text + "\n").encode("utf-8"))
        self._proc.stdin.flush()

    def request(self, method: str, params: dict | None = None):
        """Send a request and wait for the response with the same id. Raises McpError for an error response."""
        request_id, self._next_id = self._next_id, self._next_id + 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, **({"params": params} if params is not None else {})})
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty:
                raise TimeoutError(f"no answer to {method} within {self.timeout} seconds") from None
            if line is None:
                raise ConnectionError("the server closed the connection")
            if self.trace:
                print(f"   server -> client  {line[:200]}{' ...' if len(line) > 200 else ''}")
            message = json.loads(line)
            if message.get("id") == request_id:
                if "error" in message:
                    raise McpError(message["error"])
                return message["result"]
            # anything else (a notification, a log) is skipped here; a full client would handle it

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def initialize(self) -> dict:
        """The handshake: agree on a protocol version and exchange capabilities, then tell the server we are ready."""
        result = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                             "clientInfo": {"name": "tiny-client", "version": "1.0.0"}})
        self.server_info = result.get("serverInfo", {})
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict]:
        """All tool definitions of the server (follows `nextCursor` if the list comes in pages)."""
        tools, cursor = [], None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else None)
            tools += result["tools"]
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Call a tool: (the text of the result, is_error). A tool error is a normal result with isError=true."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")
        return text, bool(result.get("isError"))

    def tools(self, definitions: list[dict] | None = None) -> list[Tool]:
        """The server's tools as `Tool` objects for run_agent. A tool error becomes the text 'Error: ...' that the model sees."""
        def make(definition: dict) -> Tool:
            def run(**arguments):
                text, is_error = self.call_tool(definition["name"], arguments)
                return f"Error: {text}" if is_error else text
            return Tool(run, definition.get("description", ""), definition["inputSchema"], name=definition["name"])
        return [make(d) for d in (definitions if definitions is not None else self.list_tools())]

    def close(self) -> None:
        """Shut the server down the way the stdio transport describes: close its stdin and wait for it to exit."""
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()

    def __enter__(self) -> "McpClient":
        self.initialize()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
