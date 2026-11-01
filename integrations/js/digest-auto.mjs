#!/usr/bin/env node
// Automated memory digest and FTS index synchronization worker.
// Can run as a one-shot cron task or in daemon mode (--daemon).

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const BASE_DIR = path.resolve(process.env.AI_FISH_BASE || path.join(import.meta.dirname, '..', '..'));
const INBOX_DIR = path.join(BASE_DIR, 'inbox');
const RAW_DIR = path.join(BASE_DIR, 'daily', 'raw');

function log(msg) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] [digest-auto] ${msg}`);
}

function runPythonCommand(args) {
  return new Promise((resolve, reject) => {
    const memPy = path.join(BASE_DIR, 'bin', 'mem.py');
    const proc = spawn('python', ['-X', 'utf8', memPy, ...args], {
      cwd: BASE_DIR,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (d) => { stdout += d.toString('utf8'); });
    proc.stderr.on('data', (d) => { stderr += d.toString('utf8'); });

    proc.on('close', (code) => {
      if (code === 0) resolve(stdout.trim());
      else reject(new Error(`Command failed (code ${code}): ${stderr || stdout}`));
    });
  });
}

async function cycle() {
  log('Starting memory check cycle...');

  // 1. Check inbox files
  if (fs.existsSync(INBOX_DIR)) {
    const inboxFiles = fs.readdirSync(INBOX_DIR).filter((f) => f.endsWith('.json') || f.endsWith('.txt') || f.endsWith('.md'));
    if (inboxFiles.length > 0) {
      log(`Inbox has ${inboxFiles.length} pending items waiting for processing.`);
    }
  }

  // 2. Synchronize SQLite FTS database
  try {
    const syncRes = await runPythonCommand(['db', 'sync']);
    log(`Database sync: ${syncRes.split('\n')[0]}`);
  } catch (err) {
    log(`Database sync error: ${err.message}`);
  }

  // 3. Run audit check
  try {
    const auditRes = await runPythonCommand(['audit']);
    log(`Audit status: ${auditRes.split('\n')[0]}`);
  } catch (err) {
    log(`Audit warning: ${err.message}`);
  }

  log('Cycle completed.');
}

const isDaemon = process.argv.includes('--daemon');
const intervalMinutes = 30;

if (isDaemon) {
  log(`Running in daemon mode. Polling interval: ${intervalMinutes} minutes.`);
  cycle();
  setInterval(cycle, intervalMinutes * 60 * 1000);
} else {
  cycle().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
