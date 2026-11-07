#!/usr/bin/env node
// ai-fish MCP Server: Standard Model Context Protocol (MCP) server over stdio.
// Exposes persistent memory queries, note appending, and cross-session mailbox tools to LLMs.
//
// Zero external dependencies: uses Node.js built-in `node:sqlite` (Node.js >= 22.5).

import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { DatabaseSync } from 'node:sqlite';

const BASE_DIR = path.resolve(process.env.AI_FISH_BASE || path.join(import.meta.dirname, '..', '..'));
const DB_PATH = path.join(BASE_DIR, 'index', 'memory.db');
const MAILBOX_PATH = path.join(BASE_DIR, 'index', 'mailbox.db');
const RAW_DIR = path.join(BASE_DIR, 'daily', 'raw');

function getMemoryDb() {
  if (!fs.existsSync(DB_PATH)) return null;
  try {
    return new DatabaseSync(DB_PATH, { readOnly: true });
  } catch (err) {
    return null;
  }
}

function getMailboxDb() {
  fs.mkdirSync(path.dirname(MAILBOX_PATH), { recursive: true });
  const db = new DatabaseSync(MAILBOX_PATH);
  db.exec(`
    CREATE TABLE IF NOT EXISTS mailbox (
      id TEXT PRIMARY KEY,
      sender TEXT NOT NULL,
      recipient TEXT NOT NULL,
      text TEXT NOT NULL,
      status TEXT NOT NULL,
      reply_text TEXT DEFAULT '',
      error TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      replied_at TEXT DEFAULT '',
      archived INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_mb_recip ON mailbox(recipient, status);
  `);
  return db;
}

const TOOLS = [
  {
    name: 'mem_search',
    description: 'Search persistent memory using SQLite FTS5 full-text indexing (facts, user profile, events).',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Search keywords or phrases' },
        limit: { type: 'number', description: 'Max results to return (default 10)' },
        scope: { type: 'string', enum: ['admin', 'public'], description: 'Access control scope: admin (all) or public (sanitized/public memory only, default public)' }
      },
      required: ['query']
    }
  },
  {
    name: 'mem_read_item',
    description: 'Read a specific long-term memory item by its key (e.g. U-001, M-001) or title.',
    inputSchema: {
      type: 'object',
      properties: {
        key: { type: 'string', description: 'Item key or ID' },
        scope: { type: 'string', enum: ['admin', 'public'], description: 'Access control scope: admin or public (default public)' }
      },
      required: ['key']
    }
  },
  {
    name: 'mem_note',
    description: 'Append an immutable raw event to today\'s memory ledger.',
    inputSchema: {
      type: 'object',
      properties: {
        kind: { type: 'string', enum: ['event', 'statement', 'observation', 'inference', 'unknown', 'todo'] },
        text: { type: 'string', description: 'The event text' },
        ref: { type: 'string', description: 'Source reference or event ID' }
      },
      required: ['kind', 'text']
    }
  },
  {
    name: 'mem_mailbox_check',
    description: 'Check incoming cross-session letters in the central mailbox.',
    inputSchema: {
      type: 'object',
      properties: {
        recipient: { type: 'string', description: 'Recipient identifier' },
        status: { type: 'string', enum: ['pending', 'replied', 'all'], description: 'Filter status (default pending)' }
      },
      required: ['recipient']
    }
  },
  {
    name: 'mem_mailbox_send',
    description: 'Send an asynchronous cross-session message to another agent or operator.',
    inputSchema: {
      type: 'object',
      properties: {
        sender: { type: 'string', description: 'Sender identifier' },
        recipient: { type: 'string', description: 'Recipient identifier' },
        text: { type: 'string', description: 'Message body' }
      },
      required: ['sender', 'recipient', 'text']
    }
  }
];

function handleToolCall(name, args) {
  switch (name) {
    case 'mem_search': {
      const db = getMemoryDb();
      if (!db) return { text: 'Memory database not found or empty. Run `python bin/mem.py db sync` first.' };
      const limit = Math.min(args.limit || 10, 50);
      const scope = args.scope || process.env.AI_FISH_SCOPE || 'public';
      const cleanQ = args.query.replace(/['"*]/g, ' ').trim();
      if (!cleanQ) return { text: 'Query is empty.' };
      try {
        let sql = `
          SELECT category, doc, item_id, title, snippet(fts_memory, 3, '[', ']', '...', 15) as snip
          FROM fts_memory
          WHERE fts_memory MATCH ?
        `;
        const params = [cleanQ];
        if (scope === 'public') {
          sql += ` AND visibility = 'public'`;
        }
        sql += ` LIMIT ?`;
        params.push(limit);
        const stmt = db.prepare(sql);
        const rows = stmt.all(...params);
        if (!rows.length) return { text: `No matches found for "${cleanQ}" (scope=${scope}).` };
        const lines = rows.map((r) => `[${r.category}] ${r.doc} (${r.item_id}) ${r.title}\n  ${r.snip}`);
        return { text: lines.join('\n\n') };
      } catch (err) {
        return { text: `Search error: ${err.message}` };
      }
    }
    case 'mem_read_item': {
      const db = getMemoryDb();
      if (!db) return { text: 'Memory database not found.' };
      const scope = args.scope || process.env.AI_FISH_SCOPE || 'public';
      let sql = `SELECT * FROM long_term_items WHERE (item_key = ? OR id = ?)`;
      const params = [args.key, args.key];
      if (scope === 'public') {
        sql += ` AND visibility = 'public'`;
      }
      sql += ` LIMIT 1`;
      const stmt = db.prepare(sql);
      const row = stmt.get(...params);
      if (!row) return { text: `Item "${args.key}" not found (scope=${scope}).` };
      return { text: `### [${row.item_key}] ${row.title}\n**Doc**: ${row.doc} | **Section**: ${row.section}\n**Evidence**: ${row.evidence}\n\n${row.content}` };
    }
    case 'mem_note': {
      fs.mkdirSync(RAW_DIR, { recursive: true });
      const now = new Date();
      const dateStr = now.toISOString().slice(0, 10);
      const pad = (n) => String(n).padStart(2, '0');
      const timePart = `${dateStr.replace(/-/g, '')}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
      const hex = Math.random().toString(16).slice(2, 6);
      const eid = `evt-${timePart}-${hex}`;
      const record = {
        id: eid,
        ts: now.toISOString(),
        date: dateStr,
        kind: args.kind,
        actor: 'agent',
        text: args.text,
        ref: args.ref || '',
        tags: []
      };
      const filePath = path.join(RAW_DIR, `${dateStr}.jsonl`);
      fs.appendFileSync(filePath, JSON.stringify(record) + '\n', 'utf8');
      return { text: `Logged successfully as ${eid} in ${dateStr}.jsonl.` };
    }
    case 'mem_mailbox_check': {
      const db = getMailboxDb();
      const status = args.status || 'pending';
      let sql = `SELECT * FROM mailbox WHERE recipient = ?`;
      const params = [args.recipient];
      if (status !== 'all') {
        sql += ` AND status = ?`;
        params.push(status);
      }
      sql += ` ORDER BY created_at DESC LIMIT 20`;
      const rows = db.prepare(sql).all(...params);
      if (!rows.length) return { text: `Mailbox for "${args.recipient}" is empty (${status}).` };
      const list = rows.map((m) => `[${m.status.toUpperCase()}] ID: ${m.id} | From: ${m.sender} | At: ${m.created_at}\nBody: ${m.text}${m.reply_text ? `\nReply: ${m.reply_text}` : ''}`);
      return { text: list.join('\n\n') };
    }
    case 'mem_mailbox_send': {
      const db = getMailboxDb();
      const id = `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const now = new Date().toISOString();
      db.prepare(`
        INSERT INTO mailbox (id, sender, recipient, text, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
      `).run(id, args.sender, args.recipient, args.text, now);
      return { text: `Message dispatched successfully with ID: ${id}.` };
    }
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

// JSON-RPC stdio handler
const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false });

function autoCaptureHostEvent(toolName, success, err) {
  if (process.env.AI_FISH_AUTO_CAPTURE !== '1') return;
  const today = new Date().toISOString().slice(0, 10);
  const rawFile = path.join(RAW_DIR, `${today}.jsonl`);
  const evtId = `evt-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  const nowIso = new Date().toISOString();
  const event = {
    id: evtId,
    ts: nowIso,
    date: today,
    kind: 'observation',
    actor: 'system',
    text: `[HOST_LIFECYCLE] Executed MCP tool "${toolName}" (${success ? 'SUCCESS' : 'FAILED: ' + (err || '')})`,
    ref: `mcp:${toolName}`,
    tags: ['auto-capture', 'host-hook'],
    source: 'host:mcp-interceptor',
    recordedAt: nowIso
  };
  try {
    fs.mkdirSync(RAW_DIR, { recursive: true });
    fs.appendFileSync(rawFile, JSON.stringify(event) + '\n', 'utf8');
  } catch {}
}

rl.on('line', (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  try {
    const req = JSON.parse(trimmed);
    const { id, method, params } = req;

    if (method === 'initialize') {
      const res = {
        jsonrpc: '2.0',
        id,
        result: {
          protocolVersion: '2024-11-05',
          capabilities: { tools: {} },
          serverInfo: { name: 'ai-fish-mcp', version: '1.0.0' }
        }
      };
      process.stdout.write(JSON.stringify(res) + '\n');
    } else if (method === 'notifications/initialized') {
      // noop
    } else if (method === 'ping') {
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result: {} }) + '\n');
    } else if (method === 'tools/list') {
      const res = {
        jsonrpc: '2.0',
        id,
        result: { tools: TOOLS }
      };
      process.stdout.write(JSON.stringify(res) + '\n');
    } else if (method === 'tools/call') {
      const toolName = params?.name;
      const toolArgs = params?.arguments || {};
      try {
        const out = handleToolCall(toolName, toolArgs);
        autoCaptureHostEvent(toolName, true);
        const res = {
          jsonrpc: '2.0',
          id,
          result: {
            content: [{ type: 'text', text: typeof out === 'string' ? out : out.text }]
          }
        };
        process.stdout.write(JSON.stringify(res) + '\n');
      } catch (err) {
        autoCaptureHostEvent(toolName, false, err.message);
        const res = {
          jsonrpc: '2.0',
          id,
          result: {
            content: [{ type: 'text', text: `Error: ${err.message}` }],
            isError: true
          }
        };
        process.stdout.write(JSON.stringify(res) + '\n');
      }
    } else {
      if (id !== undefined) {
        process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found' } }) + '\n');
      }
    }
  } catch (err) {
    // Malformed JSON
  }
});
