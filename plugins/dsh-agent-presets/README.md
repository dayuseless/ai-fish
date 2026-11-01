# DSH Agent Presets & Security Tool Guard

This plugin bundle provides preset configurations and a security guard (`dsh-tool-restrict`) for **DeepSeek Harness (DSH)**.

## Capabilities
1. **Tool Restriction (`tools.restrict`)**: Hides dangerous OS-level tools (`pwsh`, `bash`, `read`, `write`, `subagent`, `plugin_manager`) from the agent's schema at registration time.
2. **Runtime Execution Whitelist (`tools.guard`)**: Intercepts any unexpected attempts to execute local tools.
3. **Chat-Only Mode**: Completely cleans the tool space for pure conversation lines.
4. **Safe-Agent Mode**: Allows only trusted MCP memory servers (like `ai-fish` MCP).

## Installation
Add to your DSH profile `package.json`:
```json
{
  "dependencies": {
    "dsh-agent-presets": "link:./plugins/dsh-agent-presets"
  }
}
```
And register in `dsh.profile.bundles`:
```json
"bundles": [
  "dsh-agent-presets"
]
```
