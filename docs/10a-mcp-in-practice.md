# Module 10a: MCP in Practice: Claude Desktop, GitHub Copilot and VS Code

**Goal:** connect MCP servers to three applications you actually use (Claude Desktop, the GitHub Copilot app and Visual Studio Code), check and review what is connected, and know which servers are worth adding for development.
**Time:** ~30 min. **Prerequisites:** [Module 10](10-tools-mcp.md) (what MCP is, the tiny server of the lessons, and the security section).

**Status of this handout.** The menus, file names and even the preferred configuration format of these applications change every few months. The steps below were compiled from the official documentation on **2026-11-20**; each section names its sources. They were not clicked through on a machine for this handout, so where the documentation is silent or contradicts itself the text says so. If a step differs on your screen, trust the screen and the linked page, and note the difference.

## 1. What every client needs

All three applications do the same job: start or reach an MCP server, list its tools, show them to the model, and ask you before a tool runs. Only the place of the configuration differs.

| Concept | Local server (stdio) | Remote server (HTTP) |
|---|---|---|
| Entry | A name and a **command** with **args** (and **env**): the application starts the process | A name and a **URL** (and **headers**): the application connects |
| Typical JSON | `"command": "npx", "args": ["-y", "pkg"]` | `"type": "http", "url": "https://.../mcp"` |
| Credentials | Environment variables of the process (`env`) | OAuth sign-in, or a token in a header |
| Who is trusted | The program, which runs **with your rights** | The operator of the service, who receives your data |
| Where it runs | Your machine | The vendor's cloud (Claude Desktop connectors), or your machine (the others) |

Three rules that save most of the time:

1. **Use absolute paths** for `command` and for files. Desktop applications often start with a different `PATH` than your terminal, so `node` or `python` may be "not found" although they work in PowerShell.
2. **Secrets do not go into files that are committed.** Use environment variables or the prompt mechanism of the client.
3. **Restart is part of the procedure.** After a file edit a client may need a full quit and start (Claude Desktop does), or an explicit server restart (VS Code, Copilot).

### Try it with the server of Module 10

The tiny notes server is the best first test, because you know exactly what it should do. Replace the paths with the absolute paths on your machine (on Windows, backslashes in JSON must be doubled):

```json
{ "command": "C:\\Python313\\python.exe",
  "args": ["C:\\path\\to\\llm-agents-handouts\\examples\\python\\m10_mcp_server.py"] }
```

The JavaScript twin works the same way with `node` and `m10_mcp_server.mjs`. In every client the test is the same: add the server, see the four tools (`add_note`, `list_notes`, `search_notes`, `word_count`), ask *"Save a note: the supplier meeting is on Thursday, then list my notes"*, and approve the calls. The notes live in the server process: stopping or restarting the server empties them.

## 2. Claude Desktop

Sources: [connect local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers), [connect remote servers](https://modelcontextprotocol.io/docs/develop/connect-remote-servers), the help-center articles on [local MCP servers](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop) and [custom connectors](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp), and [debugging](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging).

Claude Desktop has **three** ways to add a server:

| Way | For | Where |
|---|---|---|
| **Configuration file** | Local (stdio) servers | `claude_desktop_config.json` |
| **Custom connector** | Remote servers | The Connectors page of the settings, not the JSON file |
| **Desktop extension** (`.mcpb`) | Local servers as a one-click package | The Extensions page of the settings |

**Add a local server (the file).**

1. Open the Claude menu, then **Settings...** (the one of the menu bar, not the one inside the window), then **Developer**, then **Edit Config**. The button creates the file if it does not exist. On Windows the file is `%APPDATA%\Claude\claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`).
2. Add the server under `mcpServers`:

   ```json
   { "mcpServers": {
       "notes": { "command": "C:\\Python313\\python.exe",
                  "args": ["C:\\path\\to\\llm-agents-handouts\\examples\\python\\m10_mcp_server.py"] },
       "filesystem": { "command": "npx",
                       "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\you\\Documents"] } } }
   ```

3. **Quit Claude Desktop completely and start it again**: closing the window is not enough.
4. Servers that need secrets take them from `env`; the documentation notes that a server inherits only a limited set of environment variables.

**Add a remote server (a custom connector).** Open **Settings** (or Customize), then **Connectors**, **Add**, **Add custom connector**; enter the server's URL; choose how to authenticate (sign in, request headers with an API key or token, or none) and confirm. Points from the help center that matter:

- The connection is made **from Anthropic's cloud, not from your computer**. The server must be reachable on the public internet on the standard HTTPS port (443). A server on `localhost`, or on a private network, cannot be added this way.
- Custom connectors are available on free and paid plans; the free plan is limited to one custom connector. On Team and Enterprise plans an owner adds the connector for the organization first, and members then connect to it.
- The documentation does not describe remote servers in the JSON file; the two mechanisms are separate.

**Add an extension.** Settings, the Desktop app section, **Extensions**, **Browse extensions**, **Install**. A `.mcpb` file of your own is installed from the advanced settings of the same page (Extension Developer, **Install Extension...**). The packaging format and tools are at [github.com/anthropics/mcpb](https://github.com/anthropics/mcpb).

**Check and review.**

- In a chat, the **+** button at the lower left of the input box, then **Connectors**, lists what is connected and offers per-conversation toggles. **Manage connectors** opens a server and shows its tools. Remote connectors let you enable or disable single tools there; the help center suggests disabling the tools a task does not need, and a "tool access" mode (*Auto* or *On demand*) when many connectors are connected.
- When Claude wants to call a tool, the application asks for approval; you can always deny. Use **Allow always** only for servers you trust and tools that do no harm.
- Logs: `%APPDATA%\Claude\logs` on Windows (`~/Library/Logs/Claude` on macOS). `mcp.log` holds the connection log, and `mcp-server-NAME.log` the stderr of each server. In PowerShell: `Get-Content "$env:AppData\Claude\logs\mcp*.log" -Tail 50`.
- Remove a connector from the Connectors page (its menu, or *Remove*). The documentation describes no UI for removing a *local* server: delete its entry from `claude_desktop_config.json` and restart.

**When it does not work.**

| Symptom | Likely cause and fix |
|---|---|
| Server does not appear | JSON syntax error (a trailing comma), a relative path, or the app was not fully restarted; read `mcp.log` |
| "ENOENT" or "not found" on Windows | `npx` or `node` not found: check `node --version`, install Node LTS, make sure `%APPDATA%\npm` exists, or give the absolute path of the command |
| Tool calls fail silently | Run the same command in PowerShell and read `mcp-server-NAME.log` |
| A script prints extra text | A server must write only protocol messages to stdout: log to stderr (Module 10) |
| Debugging a server on its own | Use the **MCP Inspector**, below |

## 3. GitHub Copilot

Sources: [GitHub Copilot MCP overview](https://docs.github.com/en/copilot/concepts/customizations/mcp), [customize the GitHub Copilot app](https://docs.github.com/en/copilot/how-tos/github-copilot-app/customize-github-copilot-app), [add MCP servers to Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers), [allowing tools in Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/allowing-tools).

"GitHub Copilot" is several products. The **GitHub Copilot app** is the desktop application for agent-driven development; at the time of checking, the download page linked a macOS build and **Windows availability could not be confirmed**, so check the current downloads first. **GitHub Desktop**, the Git client, has no MCP support: its documentation covers only Copilot's help with commit messages and conflicts. The other Copilot surfaces (the CLI, the cloud agent, VS Code, Visual Studio, JetBrains) are separate clients that can share configuration with the app.

**In the Copilot app.** Open **Customize** in the sidebar, then **MCP**: browse or add a server, and open **Installed** to manage it. The documentation states that servers already configured **for your repositories or for Copilot CLI** are picked up automatically. The documentation does not describe an app-specific configuration file, a tool-approval screen or a connection log for the app. That makes the Copilot CLI files the practical, documented way to configure what the app reads.

**The file** (Copilot CLI, shared): `~/.copilot/mcp-config.json` for your user, or `.mcp.json` / `.github/mcp.json` in a project (loaded only after you trust the folder). The format is the portable `mcpServers` form:

```json
{ "mcpServers": {
    "notes":    { "type": "local", "command": "C:\\Python313\\python.exe",
                  "args": ["C:\\path\\to\\llm-agents-handouts\\examples\\python\\m10_mcp_server.py"], "tools": ["*"] },
    "context7": { "type": "http", "url": "https://mcp.context7.com/mcp", "tools": ["*"] } } }
```

`tools` lists which of the server's tools may be used (`["*"]` means all; list names to restrict).

**The command line** (Copilot CLI) adds and checks servers without editing the file:

```powershell
copilot mcp add notes -- C:\Python313\python.exe C:\path\to\llm-agents-handouts\examples\python\m10_mcp_server.py
copilot mcp list                 # all configured servers
copilot mcp get notes            # one server, with its configuration
```

Inside an interactive session `/mcp` shows a dashboard and `/mcp show notes` the tools of one server. Approvals are controlled with `--allow-tool` and `--deny-tool` (a deny rule wins over an allow rule); saved approvals are kept in `~/.copilot/permissions-config.json`. The options that allow everything (`--allow-all`, `--yolo`) are documented as meant for isolated environments only.

**Two things that differ on GitHub itself.**

- The **Copilot cloud agent** (the agent that works on issues in GitHub) takes its MCP servers from the repository settings (*Settings*, *Copilot*, *MCP servers*) and, according to the documentation, **calls the configured tools autonomously without asking**. The `tools` allowlist is the only gate, so list only read-only tools there. Secrets for it must be named with the prefix `COPILOT_MCP_`.
- Organizations that use Copilot Business or Enterprise control MCP through the **"MCP servers in Copilot"** policy, preferably with an allowlist of servers. The policy governs Business and Enterprise users; individual plans are not governed by it. See [MCP management](https://docs.github.com/en/copilot/concepts/enterprise/mcp-management).

## 4. Visual Studio Code

Sources: [Add and use MCP servers in VS Code](https://code.visualstudio.com/docs/copilot/customization/mcp-servers), [manage MCP servers](https://code.visualstudio.com/docs/agents/run/manage-mcp-servers), the [configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration) and [approvals](https://code.visualstudio.com/docs/agents/run/approvals) (pages updated 2026-11-18).

**Two formats exist at the same time, and the documentation is in transition.** The current pages describe a **Copilot harness** that reads the portable `mcpServers` files of section 3 (`.mcp.json` in the workspace root, `~/.copilot/mcp-config.json` for the user) and call the older editor-managed files (`.vscode/mcp.json` and the user-profile `mcp.json`, with a top-level `servers`) the **Local harness**, which is described as deprecated and to be removed in February 2027. Older articles, and some GitHub pages, still describe only `.vscode/mcp.json`. The safe route: add servers with the guided command below and let VS Code write the file that your version prefers.

**Add a server.**

1. Command palette (`Ctrl+Shift+P`), **MCP: Add Server**. The guided flow offers an HTTP URL, a command, or an npm package, pip package or Docker image, and can import servers from another application. Review the generated command before accepting it.
2. Or **Chat: Open Customizations**, then **MCP Servers**, then **Add Server**.
3. Or edit the file by hand. The legacy workspace file, which has the advantage that the editor knows it:

   ```json
   { "servers": {
       "notes":    { "type": "stdio", "command": "C:\\Python313\\python.exe",
                     "args": ["C:\\path\\to\\llm-agents-handouts\\examples\\python\\m10_mcp_server.py"] },
       "context7": { "type": "http", "url": "https://mcp.context7.com/mcp" } } }
   ```

   The legacy format supports `inputs` for secrets: a `promptString` input with `"password": true` is asked for once and stored securely, and referenced as `${input:id}` (for example in a `headers` value). The portable format does not support `inputs`; it uses `${NAME}` references to environment variables.
4. A link of the form `vscode:mcp/install?...` installs from a web page, but opens a review screen first: it never installs silently.

**Check and review.**

| Task | How |
|---|---|
| List servers and their state | Command palette, **MCP: List Servers**; or the **MCP Servers** page of the Customizations editor (an enabled switch and a menu per server) |
| Start, stop, restart, sign in, enable or disable, uninstall | The same list: select a server and choose the action |
| Read the server's log | The list, select the server, **Show Output** |
| Edit a server | Select it in the Customizations editor, change command, arguments, environment or URL and headers, save; *Other Properties* opens the JSON |
| See and limit the tools | The **Tools** tab of the Customizations editor, or **Configure Tools** in the chat input (Local harness); choose single tools or groups |
| Use a tool by name | Type `#` in the chat input and pick the tool (the agent mode of chat is needed) |
| Trust | A workspace file inherits **Workspace Trust**: in Restricted Mode the servers do not start. Other sources may ask when a server first starts or after its configuration changes. **MCP: Reset Trust** clears these decisions |
| Approvals of tool calls | The prompt offers **Allow Once** or **Skip**, and a wider scope (this session, or always) when offered. **Chat: Manage Tool Approval** reviews saved approvals; **Chat: Reset Tool Confirmations** clears client-managed ones |

First test: ask *"Use the notes tools to save a note and list my notes"*, expand the tool call in the chat and check the result. The documentation suggests the same pattern with a low-risk server such as Microsoft Learn.

Good to know:

- **Review a repository's MCP file before you trust the repository.** A stdio entry in `.mcp.json` or `.vscode/mcp.json` is a command that runs on your machine. The documentation says not to bypass Restricted Mode for a repository you have not reviewed.
- The `tools` list does not bypass approvals, and a server's `readOnlyHint` is no substitute for an approval policy.
- Local servers can run in a **sandbox** (`sandboxEnabled`), but only on macOS and Linux; the documentation says it is not available on Windows.
- Organizations control MCP with the setting `chat.mcp.access` and managed allowlists. Other settings of the `chat.mcp.*` family cover discovery of servers configured in other applications (`chat.mcp.discovery.enabled`) and automatic starting (`chat.mcp.autostart`).
- Sampling requests (a server asking the editor's model to generate text) have their own prompt with **Allow Once**, **Always Allow for This Server** or **Skip**.

## 5. The MCP Inspector, for any server

The **Inspector** is a web tool that connects to a server directly, without a model: it lists the tools, lets you call them with your own arguments, and shows the raw messages. It is the first thing to try when a client says "failed to start".

```powershell
npx @modelcontextprotocol/inspector C:\Python313\python.exe C:\path\to\llm-agents-handouts\examples\python\m10_mcp_server.py
```

The command prints a local URL with a one-time token and opens a browser. It needs a recent Node.js version (see its [documentation](https://modelcontextprotocol.io/docs/2026-07-28/tools/inspector)). The Inspector stores secrets that you enter (OAuth tokens, `env` values) on your disk, unencrypted unless it can use a keychain; use test credentials.

## 6. Servers worth knowing

All of these are public projects with their own risks; read section 7 before connecting any of them. Run commands and URLs are the ones in the cited documentation on 2026-11-20.

| Server | What it gives an agent | Run | Link |
|---|---|---|---|
| **GitHub** (official) | Repositories, issues, pull requests, code search, Actions | Remote `https://api.githubcopilot.com/mcp/` (OAuth, or a token in an `Authorization` header), or local: `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server` | [github/github-mcp-server](https://github.com/github/github-mcp-server) |
| **Context7** | Current, version-specific documentation of libraries and frameworks (below) | Remote `https://mcp.context7.com/mcp`; API key optional | [upstash/context7](https://github.com/upstash/context7), [context7.com](https://context7.com) |
| **Microsoft Learn** | Search and fetch of Microsoft and Azure documentation, and code samples | Remote `https://learn.microsoft.com/api/mcp`, no authentication | [MCP overview](https://learn.microsoft.com/en-us/training/support/mcp) |
| **Azure MCP server** | Working with Azure resources, with your Azure sign-in (`az login`) | Local: `npx -y @azure/mcp@latest server start`; the repository moved to `microsoft/mcp` | [microsoft/mcp](https://github.com/microsoft/mcp) |
| **Playwright** | Browser automation through accessibility snapshots, for testing and web tasks | Local: `npx @playwright/mcp@latest` | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) |
| **Reference servers** | Filesystem, Git, Fetch, Memory, Sequential Thinking, Time: simple servers for learning and small jobs | For example `npx -y @modelcontextprotocol/server-memory`, `uvx mcp-server-git` | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) |
| **Supabase** (official) | Database, migrations, logs, documentation of a project | Remote `https://mcp.supabase.com/mcp` (OAuth), scoped with query parameters | [Supabase MCP guide](https://supabase.com/docs/guides/getting-started/mcp) |
| **Sentry** (official) | Errors and issues of your projects | Remote `https://mcp.sentry.dev/mcp` (OAuth), optionally scoped to one project | [mcp.sentry.dev](https://mcp.sentry.dev/) |

Notes on the table:

- **Windows and `npx`.** The reference servers' documentation says to wrap `npx` in `cmd /c` on Windows: `"command": "cmd", "args": ["/c", "npx", "-y", "..."]`.
- Some servers once kept in the reference repository (GitHub, GitLab, PostgreSQL, SQLite, Slack, Sentry and others) were archived there; use the vendor's maintained server instead. The old copies are in [servers-archived](https://github.com/modelcontextprotocol/servers-archived).
- **Finding more:** the official [MCP Registry](https://registry.modelcontextprotocol.io) lists published servers, with the command or URL to run each. It is a catalogue, not a review: a name there says who published a server, not that it is safe.

### GitHub MCP server in a little more detail

- **Remote or local.** The hosted endpoint needs no installation and signs in with OAuth in clients that support it. The documentation of the server says that remote OAuth is **not currently supported in Claude Desktop**, which therefore uses the local Docker form with a personal access token (the token variable is passed through `env`).
- **Token.** Create a **fine-grained** personal access token, restricted to the repositories you need, and give it only the permissions you are comfortable granting; the README names `repo`, `read:packages` and `read:org` as the minimum of its classic-token guidance.
- **Limit what the agent can do.** `--read-only` (local) or the `X-MCP-Readonly` header / `/readonly` path (remote) removes the write tools. `--toolsets` (or `X-MCP-Toolsets`) selects groups such as `repos`, `issues` and `pull_requests`, and `--tools` selects single tools. A **lockdown mode** filters content from users without push access; the README calls it best-effort, not a security boundary.
- **Why this matters:** issues, pull requests and comments are text written by other people, and the agent reads them (section 7).

### Context7 in one paragraph

Language models know libraries as they were at training time, so they suggest deprecated functions and invented options. **Context7** is a documentation index with an MCP front end: it has two tools, `resolve-library-id` (find the library) and `query-docs` (fetch the relevant, version-specific passages and examples), and the agent puts the result into its context. In practice you add the server and write *"... use context7"* at the end of a request (or name a library such as `/supabase/supabase`, or a version in the prompt). No key is needed to start; a free API key raises the rate limits. The documentation index is community-contributed and, as the project itself says, cannot be guaranteed to be accurate, complete or secure, so treat the returned text as untrusted input (section 7) and check anything important against the official documentation. For Microsoft and Azure topics, the Learn server above is the official source.

## 7. Using servers safely

Module 10 explained the attacks; in practice they come down to these habits:

| Habit | Why |
|---|---|
| **Read what you add.** Check the publisher, the command or URL, and the tools list before the first start | A local server runs with your rights; a remote one receives your data |
| **Pin versions.** Prefer a fixed version over `@latest` for anything you rely on | A moving package can change after you reviewed it (a "rug pull") |
| **Least privilege.** Read-only mode, a few toolsets, a fine-grained token, a database user that can only read, one project instead of the whole account | A tool can do everything its credentials allow, whoever asked for it |
| **Keep approvals on** for tools that write, send, delete or spend, and read the arguments before you allow | The approval is a gate that does not depend on the model's judgement. Be cautious with "always allow" |
| **Treat returned text as untrusted.** Issues, pull requests, web pages, documentation and database rows can all contain instructions | The model cannot tell your instruction from text inside a tool result. The Supabase guide documents an example of an injected instruction in a support ticket |
| **Separate the dangerous combination.** Private data, untrusted content and an external channel in one agent session is how data leaks | Remove one of the three (Module 10, section 4) |
| **Mind autonomous modes.** The Copilot cloud agent calls allowed tools without asking; Copilot CLI's allow-all options skip approvals | Allow only read-only tools there, and use isolated environments |
| **Keep secrets out of files that are committed;** redact tokens before sharing logs | Configuration files end up in repositories and screenshots |

Playwright's own documentation states that it is not a security boundary, and that one of its tools runs arbitrary JavaScript; the Azure MCP server's documentation warns that autonomous or misconfigured clients may perform destructive actions with the rights of your Azure sign-in. The same holds for most servers that can change something.

## Key takeaways

- Every client stores the same facts: a name, a command with arguments or a URL, and credentials. Claude Desktop uses `claude_desktop_config.json` for local servers and a settings page for remote ones; Copilot uses `mcpServers` files (shared by the Copilot CLI, the app and recent VS Code); VS Code adds a guided **MCP: Add Server** and still knows the older `.vscode/mcp.json`.
- Use absolute paths and restart as instructed; check connections in the tools list, the server's log and the Inspector, in that order of effort.
- Claude Desktop's remote connectors connect from the vendor's cloud, so a server on your own machine can be added only as a local server.
- Approvals are your gate. Be most careful where they do not exist (the Copilot cloud agent) or are easy to switch off.
- Start with a few well-known servers (GitHub with read-only mode, Context7 or Microsoft Learn for documentation), add one at a time, and read what each can do.

## Exercises

1. Connect `m10_mcp_server.py` to Claude Desktop, to the Copilot CLI (`copilot mcp add`) and to VS Code. In which client do you see the tool list first, and where do you find its log?
2. Break the entry on purpose (a wrong path, then invalid JSON). What does each client show, and which log or panel names the cause?
3. Run the Inspector against the notes server and call `add_note` without the `text` argument. Compare the result with the protocol error and the tool error of Module 10.
4. Add the GitHub MCP server in read-only mode with a fine-grained token limited to one test repository. Ask the agent to list open issues, then ask it to create one: what happens, and where would you see the refusal?
5. Add Context7 or the Microsoft Learn server and ask about a library function that changed recently, once with the server and once without. Compare the answers with the official documentation.
6. Use the evil variant of the notes server (`MCP_DEMO_VARIANT=evil`, set in the `env` of the entry) in one client. Does the client show you the changed tool description before you approve a call?

## Further reading

- Claude Desktop: [connect local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers), [connect remote servers](https://modelcontextprotocol.io/docs/develop/connect-remote-servers), [debugging](https://modelcontextprotocol.io/docs/2026-07-28/tools/debugging), [custom connectors](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp), [local MCP servers and extensions](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
- GitHub Copilot: [MCP overview](https://docs.github.com/en/copilot/concepts/customizations/mcp), [the Copilot app](https://docs.github.com/en/copilot/how-tos/github-copilot-app/customize-github-copilot-app), [Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers), [cloud agent](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/configure-mcp-servers), [organization policy](https://docs.github.com/en/copilot/concepts/enterprise/mcp-management)
- VS Code: [MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers), [manage MCP servers](https://code.visualstudio.com/docs/agents/run/manage-mcp-servers), [configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration), [approvals](https://code.visualstudio.com/docs/agents/run/approvals)
- Tools and catalogues: the [MCP Inspector](https://github.com/modelcontextprotocol/inspector), the [MCP Registry](https://registry.modelcontextprotocol.io), the [reference servers](https://github.com/modelcontextprotocol/servers), [Playwright MCP](https://github.com/microsoft/playwright-mcp), the [Azure MCP server](https://github.com/microsoft/mcp)

**Next:** Module 11: Frameworks landscape (coming next)
