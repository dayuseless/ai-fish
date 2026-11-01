// DSH Security Guard: Restrict dangerous local execution & filesystem tools.
//
// Dual-layer protection:
//   1) tools.restrict(): hides local tools from the LLM tool schema at registration time.
//   2) tools.guard(): strict runtime whitelist intercepting any unauthorized calls.

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

export const name = 'dsh-tool-restrict';
export const inject = ['tools'];

/**
 * Dangerous local execution / filesystem / subagent tools that should NEVER enter
 * autonomous companion or untrusted chat sessions.
 */
export const LOCAL_EXECUTION_TOOLS = [
  // Shell / process execution
  'pwsh', 'bash', 'terminal_open', 'terminal_send', 'terminal_read', 'terminal_signal', 'terminal_close', 'terminal_list',
  // Filesystem read / write / edit
  'read', 'read_image', 'write', 'edit', 'str_replace_editor', 'working_directory', 'create_worktree',
  // Search
  'glob', 'grep',
  // Runtime loading & code evaluation
  'load_workspace_dependencies',
  // Subagents and orchestration (can indirectly acquire shell)
  'subagent', 'subagent_fork', 'list_subagent_models', 'subagent_codex', 'subagent_claude_code',
  'send_message', 'interrupt_agent', 'list_agents', 'spawn_teammate', 'wait_agent',
  'team_task_create', 'team_task_get', 'team_task_list', 'team_task_update',
  'workflow', 'ralph',
  // Plugin & Cordis internals
  'cordis_inspect_list', 'cordis_inspect_query',
  'plugin_manager', 'plugin_market',
  'dsh_snapshot', 'dsh_rollback', 'incident_resolved',
  // Background jobs & goals
  'job_list', 'job_output', 'job_kill', 'skill', 'present',
  'get_goal', 'create_goal', 'update_goal',
  'schedule_create', 'schedule_list', 'schedule_update', 'schedule_delete',
  // Session queries
  'session_search', 'session_trace', 'session_event_read', 'session_event_search', 'session_event_trace',
  // MCP resource exploration (can read unauthorized local files)
  'list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource',
];

const SAFE_EXACT = new Set([
  'ask_user_question',
  'todo_write',
]);

export function apply(ctx, config = {}) {
  // Mode 1: Chat-only (Zero tools exposed, safe communication line)
  if (config && config.mode === 'chat-only') {
    ctx.tools.restrict({ allow: [] });
    ctx.tools.guard(() => 'This is a chat-only session: no tools are permitted.');
    return;
  }

  // Mode 2: Guarded agent (Hide dangerous tools from schema)
  for (const toolName of LOCAL_EXECUTION_TOOLS) {
    try {
      ctx.tools.restrict({ deny: [toolName] });
    } catch {}
  }

  // Runtime guard whitelist
  const allowedPrefixes = config.allowedPrefixes || ['mcp__ai-fish__', 'mcp__memory__'];
  ctx.tools.guard((tool) => {
    if (SAFE_EXACT.has(tool.name)) return;
    for (const prefix of allowedPrefixes) {
      if (tool.name.startsWith(prefix)) return;
    }
    return `Security Policy: Tool "${tool.name}" is restricted by dsh-tool-restrict.`;
  });
}
