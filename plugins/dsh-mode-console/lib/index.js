// DSH Mode Console Plugin
// Exposes volatile settings namespace for runtime agent mode switching.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import z from '@deepseek-ai/schemastery';

const DIAG = process.env.AGENT_MODE_DIAG ?? path.join(os.tmpdir(), 'dsh-mode-plugin.log');

function diag(msg) {
  if (!DIAG) return;
  try {
    fs.mkdirSync(path.dirname(DIAG), { recursive: true });
    fs.appendFileSync(DIAG, `[${new Date().toISOString()}] ${msg}\n`);
  } catch {}
}

export const name = 'dsh-mode-console';
export const inject = ['settings'];
export const NAMESPACE = 'agent-mode';

export const Config = z.object({
  mode: z.union([
    z.const('interactive'),
    z.const('chat-only'),
    z.const('autonomous'),
    z.const('reserved')
  ]).default('interactive').extra('volatile', true),
  adminId: z.string().description('Admin identifier (optional)').extra('volatile', true),
});

export function apply(ctx) {
  diag(`apply called; namespace=${NAMESPACE}`);
}
