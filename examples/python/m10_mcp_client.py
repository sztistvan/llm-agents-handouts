"""Module 10 lesson: the Model Context Protocol, from the client's side.

Part 1 starts the hand-written server (m10_mcp_server.py) and prints the raw JSON-RPC lines of the whole conversation: the
handshake, the list of tools, a call, and the two kinds of errors. Part 2 hands the server's tools to run_agent, which does
not know they are remote. Part 3 starts the JavaScript server of the same course: a protocol is what lets a client and a
server in different languages work together. Run:  python examples/python/m10_mcp_client.py
"""
import shutil
import sys
from pathlib import Path

from agent import run_agent
from mcp_client import McpClient, McpError

EXAMPLES = Path(__file__).resolve().parents[1]
PYTHON_SERVER = [sys.executable, str(EXAMPLES / "python" / "m10_mcp_server.py")]
NODE_SERVER = ["node", str(EXAMPLES / "js" / "m10_mcp_server.mjs")]

if __name__ == "__main__":
    print("1. The conversation, line by line (one JSON-RPC message per line over the server's stdin/stdout)\n")
    client = McpClient(PYTHON_SERVER, trace=True)
    print("   -- handshake")
    client.initialize()
    print("\n   -- what can the server do?")
    definitions = client.list_tools()
    print("\n   -- call a tool")
    print("   result:", client.call_tool("add_note", {"text": "supplier meeting on Thursday"}))
    print("\n   -- a PROTOCOL error: the tool does not exist (a JSON-RPC error response)")
    try:
        client.call_tool("delete_everything", {})
    except McpError as exc:
        print("   raised McpError:", exc)
    print("\n   -- a TOOL error: the call is valid, the tool reports a problem inside a normal result (isError: true)")
    print("   result:", client.call_tool("add_note", {}))
    client.close()

    print(f"\n2. The same tools in an agent: {[d['name'] for d in definitions]}")
    with McpClient(PYTHON_SERVER) as client:
        tools = client.tools()
        print("   user: Save a note that the supplier meeting is on Thursday. How many words has 'the quick brown fox'?")
        print("   agent:", run_agent("Save a note that the supplier meeting is on Thursday. How many words has 'the quick brown fox'?", tools, max_steps=6))
        print("   user: What did I note about the supplier?")
        print("   agent:", run_agent("What did I note about the supplier?", tools, max_steps=6))
        print("   (the notes live in the server process: a new McpClient starts a new server with no notes)")

    print("\n3. The JavaScript server of the same course, from this Python client")
    if shutil.which("node"):
        with McpClient(NODE_SERVER) as other:
            print("   server:", other.server_info, "| tools:", [t["name"] for t in other.list_tools()])
            print("   add_note ->", other.call_tool("add_note", {"text": "written through a Python client"})[0])
    else:
        print("   node is not installed: skipped")
