# DSH Mode Console Plugin (`dsh-mode-console`)

A settings UI and mode control plugin for **DeepSeek Harness (DSH)** and the Cordis runtime architecture.

## Overview
Exposes runtime mode controls and state inspection within the DeepSeek Harness settings configuration panel. It allows operators to dynamically adjust agent autonomy, tool accessibility, and operating modes without modifying code.

## Modes Supported
- `interactive`: Standard interactive assistant mode with standard tool availability.
- `chat-only`: Pure conversation mode with all execution tools suppressed.
- `autonomous`: Goal-driven agent loop with background step progression.
- `reserved`: Passive standby mode (monitoring/logging incoming events without active invocation).

## Dependencies & Prerequisites

| Requirement | Version / Specification | Purpose |
| :--- | :--- | :--- |
| **Runtime** | DeepSeek Harness (DSH) >= 0.2.0-rc.2 (Cordis framework) | Host runtime |
| **`@deepseek-ai/schemastery`** | `^3.18.1` | Schema typing and settings UI form generator |

## Installation & Configuration

### 1. Add Dependency to DSH Profile
In your DSH profile `package.json` (e.g. `~/.dsh/package.json`):
```json
{
  "dependencies": {
    "@deepseek-ai/schemastery": "^3.18.1",
    "dsh-mode-console": "link:./plugins/dsh-mode-console"
  }
}
```

Install the dependencies:
```bash
npm install
```

### 2. Register Bundle in DSH Configuration
Add `dsh-mode-console` to the `bundles` list in your DSH configuration (e.g. `dsh.profile.bundles`):
```json
"bundles": [
  "dsh-mode-console"
]
```

### 3. Patch Configuration (`cordis.patch.yml`)
The bundle automatically merges into the Cordis service container:
```yaml
$action: merge
plugins:
  group:settings:
    dsh-mode-console:
      $category: mode
      defaultMode: interactive
```
