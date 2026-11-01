// Self-test for ai-fish-mcp stdio server
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import path from 'node:path';
import readline from 'node:readline';

const serverPath = path.resolve(import.meta.dirname, '..', 'index.js');
const baseDir = path.resolve(import.meta.dirname, '..', '..');

const proc = spawn('node', [serverPath], {
  env: { ...process.env, AI_FISH_BASE: baseDir },
  stdio: ['pipe', 'pipe', 'inherit']
});

const rl = readline.createInterface({ input: proc.stdout });

let step = 0;

rl.on('line', (line) => {
  const msg = JSON.parse(line);
  if (step === 0) {
    assert.equal(msg.id, 1);
    assert.equal(msg.result.serverInfo.name, 'ai-fish-mcp');
    step = 1;
    // Request tools list
    proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' }) + '\n');
  } else if (step === 1) {
    assert.equal(msg.id, 2);
    assert.ok(Array.isArray(msg.result.tools));
    const toolNames = msg.result.tools.map((t) => t.name);
    assert.ok(toolNames.includes('mem_search'));
    assert.ok(toolNames.includes('mem_note'));
    assert.ok(toolNames.includes('mem_mailbox_check'));
    assert.ok(toolNames.includes('mem_mailbox_send'));
    console.log('MCP self-test passed successfully! Found tools:', toolNames);
    proc.kill();
    process.exit(0);
  }
});

// Send initialize
proc.stdin.write(JSON.stringify({
  jsonrpc: '2.0',
  id: 1,
  method: 'initialize',
  params: { clientInfo: { name: 'test-client', version: '1.0' } }
}) + '\n');
