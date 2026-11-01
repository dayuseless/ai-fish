#!/usr/bin/env node
// ai-fish CLI Admin Tool (Node.js)
// Fast, dependency-free operator CLI for memory search, mailbox, and system stats.

import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const BASE_DIR = path.resolve(process.env.AI_FISH_BASE || path.join(import.meta.dirname, '..', '..'));
const DB_PATH = path.join(BASE_DIR, 'index', 'memory.db');
const MAILBOX_PATH = path.join(BASE_DIR, 'index', 'mailbox.db');

function printUsage() {
  console.log(`ai-fish Admin CLI (Node.js)
Usage:
  node admin.mjs status               # Print memory database and mailbox status
  node admin.mjs search <query>       # Full-text search across memory facts and events
  node admin.mjs mailbox list [to]    # List pending or recent messages
  node admin.mjs mailbox send <to> <text> [--from <sender>]
`);
}

function getMemoryDb() {
  if (!fs.existsSync(DB_PATH)) {
    console.error(`Memory database not found at: ${DB_PATH}\nRun: python bin/mem.py db sync`);
    return null;
  }
  return new DatabaseSync(DB_PATH, { readOnly: true });
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

const args = process.argv.slice(2);
const command = args[0];

if (!command || command === 'help' || command === '--help') {
  printUsage();
  process.exit(0);
}

switch (command) {
  case 'status': {
    console.log(`=== ai-fish System Status ===`);
    console.log(`Base directory: ${BASE_DIR}`);
    if (fs.existsSync(DB_PATH)) {
      const db = getMemoryDb();
      const itemsCount = db.prepare('SELECT COUNT(*) as c FROM items').get().c;
      const eventsCount = db.prepare('SELECT COUNT(*) as c FROM events').get().c;
      console.log(`Memory Database: ${DB_PATH} [OK]`);
      console.log(`  - Long-term items: ${itemsCount}`);
      console.log(`  - Raw events indexed: ${eventsCount}`);
    } else {
      console.log(`Memory Database: Not initialized (run python bin/mem.py db sync)`);
    }

    if (fs.existsSync(MAILBOX_PATH)) {
      const db = getMailboxDb();
      const pendingCount = db.prepare('SELECT COUNT(*) as c FROM mailbox WHERE status = "pending"').get().c;
      const totalCount = db.prepare('SELECT COUNT(*) as c FROM mailbox').get().c;
      console.log(`Mailbox Database: ${MAILBOX_PATH} [OK]`);
      console.log(`  - Pending messages: ${pendingCount}`);
      console.log(`  - Total messages: ${totalCount}`);
    } else {
      console.log(`Mailbox Database: Not initialized`);
    }
    break;
  }

  case 'search': {
    const query = args[1];
    if (!query) {
      console.error('Error: query argument required.');
      process.exit(1);
    }
    const db = getMemoryDb();
    if (!db) process.exit(1);
    const rows = db.prepare(`
      SELECT item_key, title, section, score, snippet(items_fts, 3, '[', ']', '...', 16) AS snip
      FROM items_fts
      JOIN items ON items.key = items_fts.item_key
      WHERE items_fts MATCH ?
      ORDER BY score
      LIMIT 10
    `).all(query);

    console.log(`Search results for "${query}":`);
    if (!rows.length) {
      console.log('  No matching items found.');
    } else {
      for (const r of rows) {
        console.log(`- [${r.item_key}] ${r.title} (${r.section})`);
        console.log(`  ${r.snip.replace(/\n/g, ' ')}`);
      }
    }
    break;
  }

  case 'mailbox': {
    const sub = args[1];
    if (sub === 'list') {
      const recipient = args[2];
      const db = getMailboxDb();
      let sql = 'SELECT * FROM mailbox';
      const params = [];
      if (recipient) {
        sql += ' WHERE recipient = ?';
        params.push(recipient);
      }
      sql += ' ORDER BY created_at DESC LIMIT 20';
      const rows = db.prepare(sql).all(...params);
      if (!rows.length) {
        console.log('No messages found.');
      } else {
        for (const m of rows) {
          console.log(`[${m.status.toUpperCase()}] ${m.id} | From: ${m.sender} -> To: ${m.recipient} | ${m.created_at}`);
          console.log(`  Body: ${m.text}`);
          if (m.reply_text) console.log(`  Reply: ${m.reply_text}`);
        }
      }
    } else if (sub === 'send') {
      const to = args[2];
      const text = args[3];
      if (!to || !text) {
        console.error('Usage: admin.mjs mailbox send <to> <text> [--from <sender>]');
        process.exit(1);
      }
      const fromIdx = args.indexOf('--from');
      const sender = fromIdx !== -1 && args[fromIdx + 1] ? args[fromIdx + 1] : 'operator';
      const db = getMailboxDb();
      const id = `msg-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const now = new Date().toISOString();
      db.prepare(`
        INSERT INTO mailbox (id, sender, recipient, text, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
      `).run(id, sender, to, text, now);
      console.log(`Message dispatched with ID: ${id}`);
    } else {
      printUsage();
    }
    break;
  }

  default:
    printUsage();
    process.exit(1);
}
