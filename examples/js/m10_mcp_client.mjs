// Module 10 lesson: the Model Context Protocol, from the client's side.
//
// Part 1 starts the hand-written server (m10_mcp_server.mjs) and prints the raw JSON-RPC lines of the whole conversation: the
// handshake, the list of tools, a call, and the two kinds of errors. Part 2 hands the server's tools to runAgent, which does
// not know they are remote. Part 3 starts the Python server of the same course: a protocol is what lets a client and a
// server in different languages work together. Run:  node examples/js/m10_mcp_client.mjs
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { runAgent } from "./agent.mjs";
import { McpClient, McpError } from "./mcp_client.mjs";
import { ROOT } from "./retrieval.mjs";

export const NODE_SERVER = [process.execPath, join(ROOT, "examples", "js", "m10_mcp_server.mjs")];
const PYTHON = ["python", "python3", "py"].find((cmd) => spawnSync(cmd, ["--version"]).status === 0);
export const PYTHON_SERVER = PYTHON ? [PYTHON, join(ROOT, "examples", "python", "m10_mcp_server.py")] : null;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log("1. The conversation, line by line (one JSON-RPC message per line over the server's stdin/stdout)\n");
  let client = new McpClient(NODE_SERVER, { trace: true });
  console.log("   -- handshake");
  await client.initialize();
  console.log("\n   -- what can the server do?");
  const definitions = await client.listTools();
  console.log("\n   -- call a tool");
  console.log("   result:", await client.callTool("add_note", { text: "supplier meeting on Thursday" }));
  console.log("\n   -- a PROTOCOL error: the tool does not exist (a JSON-RPC error response)");
  try { await client.callTool("delete_everything", {}); } catch (err) { if (!(err instanceof McpError)) throw err; console.log("   raised McpError:", err.message); }
  console.log("\n   -- a TOOL error: the call is valid, the tool reports a problem inside a normal result (isError: true)");
  console.log("   result:", await client.callTool("add_note", {}));
  await client.close();

  console.log(`\n2. The same tools in an agent: ${JSON.stringify(definitions.map((d) => d.name))}`);
  client = await McpClient.start(NODE_SERVER);
  const tools = client.tools(await client.listTools());
  const first = "Save a note that the supplier meeting is on Thursday. How many words has 'the quick brown fox'?";
  console.log(`   user: ${first}`);
  console.log("   agent:", await runAgent(first, tools, { maxSteps: 6 }));
  console.log("   user: What did I note about the supplier?");
  console.log("   agent:", await runAgent("What did I note about the supplier?", tools, { maxSteps: 6 }));
  console.log("   (the notes live in the server process: a new McpClient starts a new server with no notes)");
  await client.close();

  console.log("\n3. The Python server of the same course, from this JavaScript client");
  if (PYTHON_SERVER) {
    const other = await McpClient.start(PYTHON_SERVER);
    console.log("   server:", other.serverInfo, "| tools:", (await other.listTools()).map((t) => t.name));
    console.log("   add_note ->", (await other.callTool("add_note", { text: "written through a JavaScript client" }))[0]);
    await other.close();
  } else {
    console.log("   python is not installed: skipped");
  }
}
