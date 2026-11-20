// A minimal MCP client over stdio (Module 10), written by hand (no SDK). Node's standard library only.
//
// Shared building block. Layers: llm_client -> agent (the loop) -> mcp_client -> m10_* lessons.
// `McpClient` starts a server as a subprocess, speaks JSON-RPC 2.0 (one message per line) and turns the server's tools into
// tool objects for `runAgent`, so an agent uses MCP tools exactly like local functions:
//
//     const client = await McpClient.start(["node", "examples/js/m10_mcp_server.mjs"]);
//     await runAgent("Save a note: buy milk", client.tools(await client.listTools()));
//
// The handshake is the one of the 2025-11-25 revision (and earlier): `initialize`, then the notification
// `notifications/initialized`. The newest revision (2026-07-28) removes it, see docs/10-tools-mcp.md.
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

export const PROTOCOL_VERSION = "2025-11-25";

/** A JSON-RPC error response (a protocol problem: unknown method or tool, bad request). */
export class McpError extends Error {
  constructor(error) { super(`${error.code}: ${error.message}`); this.code = error.code; }
}

export class McpClient {
  constructor(command, { env, trace = false, timeoutMs = 30000 } = {}) {
    this.trace = trace;
    this.timeoutMs = timeoutMs;
    this.nextId = 1;
    this.pending = new Map(); // request id -> { resolve, reject, timer }
    this.serverInfo = {};
    this.proc = spawn(command[0], command.slice(1), { stdio: ["pipe", "pipe", "ignore"], env: env ?? process.env });
    this.closed = new Promise((resolve) => this.proc.on("close", resolve));
    createInterface({ input: this.proc.stdout }).on("line", (line) => this.onLine(line));
    this.proc.on("close", () => {
      for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new Error("the server closed the connection")); }
      this.pending.clear();
    });
    this.proc.on("error", (err) => { for (const p of this.pending.values()) p.reject(err); });
  }

  /** Start a server and do the handshake. */
  static async start(command, options) {
    const client = new McpClient(command, options);
    await client.initialize();
    return client;
  }

  onLine(line) {
    if (this.trace) console.log(`   server -> client  ${line.slice(0, 200)}${line.length > 200 ? " ..." : ""}`);
    const message = JSON.parse(line);
    const entry = this.pending.get(message.id);
    if (!entry) return; // a notification or a log: skipped here; a full client would handle it
    this.pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.error) entry.reject(new McpError(message.error)); else entry.resolve(message.result);
  }

  send(message) {
    const text = JSON.stringify(message);
    if (this.trace) console.log(`   client -> server  ${text.slice(0, 200)}`);
    this.proc.stdin.write(text + "\n");
  }

  /** Send a request and wait for the response with the same id. Rejects with McpError for an error response. */
  request(method, params) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`no answer to ${method} within ${this.timeoutMs / 1000} seconds`)); }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.send({ jsonrpc: "2.0", id, method, ...(params !== undefined ? { params } : {}) });
    });
  }

  notify(method, params) { this.send({ jsonrpc: "2.0", method, ...(params !== undefined ? { params } : {}) }); }

  /** The handshake: agree on a protocol version and exchange capabilities, then tell the server we are ready. */
  async initialize() {
    const result = await this.request("initialize", { protocolVersion: PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: "tiny-client", version: "1.0.0" } });
    this.serverInfo = result.serverInfo ?? {};
    this.notify("notifications/initialized");
    return result;
  }

  /** All tool definitions of the server (follows `nextCursor` if the list comes in pages). */
  async listTools() {
    const tools = [];
    let cursor;
    do {
      const result = await this.request("tools/list", cursor ? { cursor } : undefined);
      tools.push(...result.tools);
      cursor = result.nextCursor;
    } while (cursor);
    return tools;
  }

  /** Call a tool: [the text of the result, isError]. A tool error is a normal result with isError=true. */
  async callTool(name, args) {
    const result = await this.request("tools/call", { name, arguments: args });
    const text = (result.content ?? []).filter((item) => item.type === "text").map((item) => item.text ?? "").join("\n");
    return [text, Boolean(result.isError)];
  }

  /** The tool definitions as tool objects for runAgent. A tool error becomes the text 'Error: ...' that the model sees. */
  tools(definitions) {
    return definitions.map((d) => ({
      name: d.name, description: d.description ?? "", parameters: d.inputSchema,
      run: async (args) => { const [text, isError] = await this.callTool(d.name, args); return isError ? `Error: ${text}` : text; },
    }));
  }

  /** Shut the server down the way the stdio transport describes: close its stdin and wait for it to exit. */
  async close() {
    this.proc.stdin.end();
    await Promise.race([this.closed, new Promise((resolve) => setTimeout(resolve, 5000))]);
    if (this.proc.exitCode === null) this.proc.kill();
  }
}
