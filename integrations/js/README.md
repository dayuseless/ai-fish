# Node.js Integrations & Utilities

Standalone, zero-dependency Node.js utility scripts designed to integrate with `ai-fish`.

## Dependencies & Requirements

| Requirement | Specification | Purpose |
| :--- | :--- | :--- |
| **Node.js** | `>= 22.5.0` | Required for native built-in `node:sqlite` database driver |
| **External npm Packages** | None (Zero external dependencies) | Uses native Node.js standard libraries only |

---

## Included Scripts

### 1. `admin.mjs`
A fast command-line management tool for querying memory and inspecting/sending mailbox messages without requiring Python.
```bash
# Print status and database statistics
node integrations/js/admin.mjs status

# Full-text search across persistent memory
node integrations/js/admin.mjs search "user preferences"

# Check messages sent to an agent
node integrations/js/admin.mjs mailbox list bot-companion

# Dispatch a new asynchronous message
node integrations/js/admin.mjs mailbox send bot-companion "Please review the new daily log."
```

### 2. `digest-auto.mjs`
Automated background task runner. It polls `inbox/` for new data, triggers FTS database synchronization via `mem.py db sync`, and runs integrity audits.
```bash
# Run a single synchronization cycle
node integrations/js/digest-auto.mjs

# Run continuously as a background daemon (every 30 minutes)
node integrations/js/digest-auto.mjs --daemon
```

### 3. `peak-gate.mjs`
Schedule-aware rate limiter and token economy gatekeeper for automated LLM bots (e.g. QQ, Telegram, Discord bridges).
- Distinguishes peak hours (strict quota) from valley/night hours (relaxed quota).
- Enforces per-minute sliding window token limits.
```javascript
import { PeakGate } from './integrations/js/peak-gate.mjs';

const gate = new PeakGate({
  peakStartHour: 9,
  peakEndHour: 23,
  peakMaxTokensPerMinute: 20000,
  valleyMaxTokensPerMinute: 60000
});

const status = gate.check(promptTokens + completionTokens);
if (!status.allowed) {
  console.warn(`Rate limit reached during ${status.isPeak ? 'peak' : 'off-peak'}! Try again in ${status.resetInMs}ms`);
}
```
