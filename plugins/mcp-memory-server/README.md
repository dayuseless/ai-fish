# ai-fish MCP Server

A zero-dependency Model Context Protocol (MCP) server that connects any MCP-compatible AI client (Claude Desktop, Cursor, Cline, Windsurf, DSH) directly to your `ai-fish` persistent memory.

## Features

- **Zero npm dependencies**: Uses Node.js native `node:sqlite` (Node.js >= 22.5).
- **Fast Full-Text Search**: Queries `index/memory.db` with SQLite FTS5 for sub-millisecond retrieval of long-term facts, preferences, and events.
- **Append-Only Event Ledger**: Directly writes raw timestamped events to `daily/raw/` adhering to the immutable seal protocol.
- **Cross-Session Mailbox**: Inter-agent messaging (`mem_mailbox_check`, `mem_mailbox_send`) for coordinating asynchronous work across distinct chat sessions.

## Exposed Tools

| Tool | Description | Parameters |
| :--- | :--- | :--- |
| `mem_search` | Search persistent memory via FTS5 index | `query` (string, required), `limit` (number, default 10) |
| `mem_read_item` | Read a specific long-term item by key (e.g. `U-001`, `M-001`) | `key` (string, required) |
| `mem_note` | Append an immutable raw event to today's memory ledger | `kind` (`event`\|`statement`\|`observation`\|`inference`\|`unknown`\|`todo`), `text` (string), `ref` (string, optional) |
| `mem_mailbox_check` | Read pending or replied letters from the inter-agent mailbox | `recipient` (string, required), `status` (`pending`\|`replied`\|`all`) |
| `mem_mailbox_send` | Send an asynchronous message to another agent or operator | `recipient` (string, required), `text` (string, required), `sender` (string, optional) |

---

## Client Configuration Examples

### 1. Claude Desktop

Add to your `claude_desktop_config.json` (on macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; on Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ai-fish": {
      "command": "node",
      "args": ["/path/to/ai-fish/plugins/mcp-memory-server/index.js"],
      "env": {
        "AI_FISH_BASE": "/path/to/ai-fish"
      }
    }
  }
}
```

### 2. Cursor

Add to `.cursor/mcp.json` in your workspace root:

```json
{
  "mcpServers": {
    "ai-fish": {
      "command": "node",
      "args": ["./plugins/mcp-memory-server/index.js"],
      "env": {
        "AI_FISH_BASE": "${workspaceFolder}"
      }
    }
  }
}
```

### 3. Cline / Roo Code

Add to Cline MCP settings:

```json
{
  "mcpServers": {
    "ai-fish": {
      "command": "node",
      "args": ["C:\\path\\to\\ai-fish\\plugins\\mcp-memory-server\\index.js"],
      "env": {
        "AI_FISH_BASE": "C:\\path\\to\\ai-fish"
      },
      "disabled": false,
      "autoApprove": [
        "mem_search",
        "mem_read_item"
      ]
    }
  }
}
```

### 4. DSH (DeepSeek Hub / Cordis Framework)

Configure via patch in your DSH configuration:

```yaml
# cordis.patch.yml
mcp:
  servers:
    ai-fish:
      command: node
      args:
        - ./plugins/mcp-memory-server/index.js
      env:
        AI_FISH_BASE: .
```

---

## Requirements

- Node.js >= 22.5.0 (for native `node:sqlite` support)
