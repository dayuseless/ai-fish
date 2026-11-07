# DSH Agent Presets & Security Tool Guard (`dsh-agent-presets`)

Preset configurations and a defense-in-depth security guard (`dsh-tool-restrict`) for **DeepSeek Harness (DSH)** and the Cordis runtime.

## Capabilities

1. **Tool Restriction (`tools.restrict`)**: Hides dangerous OS-level execution tools (`pwsh`, `bash`, `read`, `write`, `subagent`, `plugin_manager`) from the agent's registration schema.
2. **Runtime Execution Whitelist (`tools.guard`)**: Intercepts unauthorized runtime invocations with security rejections.
3. **Chat-Only Mode**: Strips all tools for clean conversational interaction.
4. **Safe-Agent Mode**: Allows only trusted MCP memory servers (such as `ai-fish` MCP) while prohibiting arbitrary filesystem or shell operations.

## Dependencies & Prerequisites

| Requirement | Version / Specification | Purpose |
| :--- | :--- | :--- |
| **Runtime** | DeepSeek Harness (DSH) >= 0.2.0-rc.2 (Cordis framework) | Host runtime |
| **External npm Packages** | None (Zero external dependencies) | Uses native ESM & Cordis bundle patch |

## Installation & Configuration

### 1. Add to DSH Profile
In your DSH profile `package.json`:
```json
{
  "dependencies": {
    "dsh-agent-presets": "link:./plugins/dsh-agent-presets"
  }
}
```

### 2. Register in DSH Profile Bundles
In your DSH profile settings:
```json
"bundles": [
  "dsh-agent-presets"
]
```

### 3. Presets Included
- `./presets/chat-only.patch.yml`: Enforces tool-free conversation.
- `./presets/safe-agent.patch.yml`: Restricts agent tool surface strictly to `ai-fish` MCP memory operations.
