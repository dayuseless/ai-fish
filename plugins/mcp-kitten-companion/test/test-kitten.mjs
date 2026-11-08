// test-kitten.mjs — Comprehensive Test Suite for Kitten Companion & MCP Server
import assert from 'node:assert';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const TEST_STATE_DIR = path.resolve(__dirname, 'temp-state');
const TEST_STATE_FILE = path.join(TEST_STATE_DIR, 'kitten.json');

process.env.AI_FISH_KITTEN_STATE = TEST_STATE_FILE;

try {
  fs.mkdirSync(TEST_STATE_DIR, { recursive: true });

  const { getKittenState, interactKitten, getKittenPromptSummary, tickKitten } = await import('../kitten-service.js');

  console.log('1. 测试初始状态加载与自然状态...');
  const state = getKittenState();
  assert.ok(state.name, '小猫必须有名字');
  assert.ok(state.location, '小猫必须有初始位置');
  assert.ok(state.action, '小猫必须有初始动作');
  console.log(`   [PASS] 名字: ${state.name}, 位置: ${state.location}`);

  console.log('2. 测试提示词单行摘要生成...');
  const summary = getKittenPromptSummary();
  assert.ok(summary.includes('【身边的小猫】'), '摘要必须包含身边的小猫前缀');
  assert.ok(summary.includes(state.name), '摘要必须包含小猫名字');
  console.log(`   [PASS] 摘要: ${summary}`);

  console.log('3. 测试自主节律推进 (tickKitten force=true)...');
  const ticked = tickKitten(state, true);
  assert.ok(ticked.lastActionAt, 'tick 必须更新时间戳');
  assert.ok(ticked.history.length > 0, 'tick 必须追加历史记录');
  console.log(`   [PASS] 新位置: ${ticked.location}, 行为: ${ticked.action}`);

  console.log('4. 测试全部交互动作...');
  const actions = ['look', 'search', 'pet', 'play', 'feed', 'snuggle', 'step_on_head'];
  for (const act of actions) {
    const res = interactKitten(act, { item: '小纸团' });
    assert.strictEqual(res.success, true, `动作 ${act} 必须成功`);
    assert.ok(res.response.length > 10, `动作 ${act} 必须有真实猫咪反馈`);
    // 保证绝无人言
    assert.ok(!res.response.includes('我说：'), '小猫绝不能说人类对话');
    console.log(`   [PASS] 动作 [${act}]: ${res.response.split('\n')[0]}`);
  }

  console.log('5. 测试起名/改名 (rename)...');
  const renameRes = interactKitten('rename', { name: '雪球' });
  assert.strictEqual(renameRes.success, true);
  assert.strictEqual(renameRes.catName, '雪球');
  const renamedState = getKittenState();
  assert.strictEqual(renamedState.name, '雪球');
  console.log(`   [PASS] 改名成功，新名字: ${renamedState.name}`);

  console.log('6. 测试 MCP stdio JSON-RPC 通信...');
  const mcpEntry = path.join(ROOT, 'index.js');
  const child = spawn(process.execPath, [mcpEntry], {
    env: { ...process.env, AI_FISH_KITTEN_STATE: TEST_STATE_FILE }
  });

  let buffer = '';
  const responses = [];

  child.stdout.on('data', (data) => {
    buffer += data.toString('utf8');
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const l of lines) {
      if (l.trim()) {
        try { responses.push(JSON.parse(l.trim())); } catch {}
      }
    }
  });

  const send = (msg) => child.stdin.write(JSON.stringify(msg) + '\n');

  // 6.1 Initialize
  send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: {} });
  await new Promise((r) => setTimeout(r, 200));
  assert.strictEqual(responses[0]?.id, 1);
  assert.strictEqual(responses[0]?.result?.serverInfo?.name, 'mcp-kitten-companion');
  console.log('   [PASS] MCP initialize 握手成功');

  // 6.2 Tools list
  send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} });
  await new Promise((r) => setTimeout(r, 200));
  assert.strictEqual(responses[1]?.id, 2);
  const toolNames = responses[1]?.result?.tools?.map((t) => t.name) || [];
  assert.ok(toolNames.includes('kitten_interact'));
  assert.ok(toolNames.includes('kitten_status'));
  console.log(`   [PASS] MCP tools/list 成功暴露: ${toolNames.join(', ')}`);

  // 6.3 Call kitten_interact (pet)
  send({
    jsonrpc: '2.0',
    id: 3,
    method: 'tools/call',
    params: { name: 'kitten_interact', arguments: { action: 'pet' } }
  });
  await new Promise((r) => setTimeout(r, 200));
  assert.strictEqual(responses[2]?.id, 3);
  const toolContent = responses[2]?.result?.content?.[0]?.text || '';
  assert.ok(toolContent.includes('【摸摸】'));
  console.log('   [PASS] MCP tools/call (kitten_interact pet) 成功执行');

  child.kill();
  console.log('\n🎉 所有小猫伴侣与 MCP 单元测试全部通过！');
} finally {
  try { fs.rmSync(TEST_STATE_DIR, { recursive: true, force: true }); } catch {}
}
