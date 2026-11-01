// Self-test for dsh-tool-restrict guard
import assert from 'node:assert/strict';
import { apply, LOCAL_EXECUTION_TOOLS } from '../tool-restrict.mjs';

function createMockContext() {
  const restricted = [];
  const guards = [];
  return {
    ctx: {
      tools: {
        restrict(policy) {
          restricted.push(policy);
        },
        guard(fn) {
          guards.push(fn);
        }
      }
    },
    restricted,
    guards
  };
}

console.log('Testing chat-only mode...');
{
  const { ctx, restricted, guards } = createMockContext();
  apply(ctx, { mode: 'chat-only' });
  assert.equal(restricted.length, 1);
  assert.deepEqual(restricted[0], { allow: [] });
  assert.equal(guards.length, 1);
  assert.match(guards[0]({ name: 'any_tool' }), /chat-only/);
}

console.log('Testing guarded mode...');
{
  const { ctx, restricted, guards } = createMockContext();
  apply(ctx, { allowedPrefixes: ['mcp__ai-fish__'] });
  assert.ok(restricted.length >= LOCAL_EXECUTION_TOOLS.length);
  assert.equal(guards.length, 1);

  const guard = guards[0];
  // Safe tools
  assert.equal(guard({ name: 'ask_user_question' }), undefined);
  assert.equal(guard({ name: 'todo_write' }), undefined);
  assert.equal(guard({ name: 'mcp__ai-fish__mem_search' }), undefined);

  // Dangerous tools should be blocked
  assert.match(guard({ name: 'pwsh' }), /restricted/);
  assert.match(guard({ name: 'write' }), /restricted/);
  assert.match(guard({ name: 'subagent' }), /restricted/);
  assert.match(guard({ name: 'plugin_manager' }), /restricted/);
}

console.log('All guard tests passed!');
