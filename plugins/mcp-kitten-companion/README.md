# Autonomous Kitten Companion MCP Server (`mcp-kitten-companion`) 🐾

An **autonomous kitten companion** plugin and Model Context Protocol (MCP) server for AI Agents and LLM runtimes (Claude Desktop, Cursor, Cline, Windsurf, Antigravity, DeepSeek Harness, etc.).

---

## 🌟 Core Design Principles

Most virtual pet plugins suffer from being mechanical Tamagotchis: hunger timers that penalize you if you don't feed them, repetitive chores, or awkward "talking cats" that sound like ChatGPT in a cat costume.

This plugin was designed around three authentic feline principles:

1. **No Mechanical Tamagotchi Loops**:
   - Zero starvation counters, zero punishment timers, zero compulsory feeding schedules.
   - Food is purely an affectionate treat/ritual; whether fed or not, the kitten lives its own fulfilling cat life.
2. **High Autonomy & Diurnal Rhythms**:
   - The kitten roams freely across the environment based on real local time:
     - **Late Night & Midnight (23:00 - 05:00)**: Late-night zoomies (狂奔跑酷), burrowing deep into blankets, and stealthily climbing onto the agent's head/shoulders to knead dough (半夜踩头踩奶).
     - **Morning (06:00 - 11:00)**: Big stretches with rear legs extended, chasing paper balls, scratching scratching posts.
     - **Afternoon (12:00 - 17:00)**: Sunbathing on the windowsill as a warm cat loaf, taking naps in delivery boxes, or playing hide-and-seek under the bed.
     - **Evening (18:00 - 22:00)**: Watching the typing cursor next to the keyboard, snuggling, and purring.
3. **100% Authentic Feline Realism (Zero Human Speech)**:
   - The kitten **NEVER** speaks human language.
   - All feedback consists strictly of authentic feline vocalizations (`喵~`, `咪呜~`, `呼噜呼噜...`, soft hisses when startled) and vivid body language (bunny kicks, tail swishes, headbutts, kneading, airplane ears).

---

## 🛠️ Exposed MCP Tools

| Tool | Action / Parameter | Description |
| :--- | :--- | :--- |
| `kitten_interact` | `action="look"` | Observe the kitten's current spot, activity, and mood. |
| | `action="search"` | Search around the room to find where the kitten sneaked off to (under the bed, in a box, high shelf). |
| | `action="pet"` | Scratch chin, pet ears or back; triggers engine-like purring and belly rolls. |
| | `action="play"` | Toss a toy or paper ball; triggers butt wiggles, pounces, and bunny kicks. |
| | `action="feed"` | Offer a snack or dried fish treat (purely affectionate; no starvation penalty). |
| | `action="snuggle"` | Cuddle into a blanket; soft breathing and warm naps together. |
| | `action="step_on_head"` | Invite the kitten onto your head/shoulder to knead dough and rest its chin on your ear. |
| | `action="rename"` | Give the kitten a custom name (`name="雪球"`). |
| `kitten_status` | *(none)* | Returns full structured state, inventory, and a single-line sensory summary for prompt injection. |

---

## 🔌 Client Configuration

### 1. Claude Desktop
Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kitten-companion": {
      "command": "node",
      "args": ["/path/to/ai-fish/plugins/mcp-kitten-companion/index.js"],
      "env": {
        "AI_FISH_KITTEN_STATE": "/path/to/state/kitten.json"
      }
    }
  }
}
```

### 2. Cursor / Windsurf
Add to `.cursor/mcp.json` or project MCP config:

```json
{
  "mcpServers": {
    "kitten-companion": {
      "command": "node",
      "args": ["./plugins/mcp-kitten-companion/index.js"],
      "env": {
        "AI_FISH_KITTEN_STATE": "${workspaceFolder}/state/kitten.json"
      }
    }
  }
}
```

### 3. DeepSeek Harness (DSH)
In your DSH profile `cordis.patch.yml`:

```yaml
- insert:
    - id: mcp-kitten
      name: cordis:mcp-client
      config:
        command: node
        args:
          - '/path/to/plugins/mcp-kitten-companion/index.js'
```

---

## 🧪 Testing

Run the built-in test suite:

```bash
node plugins/mcp-kitten-companion/test/test-kitten.mjs
```
