#!/usr/bin/env node
// kitten-companion MCP Server: Standard Model Context Protocol (MCP) server over stdio.
// Exposes autonomous kitten companion interactions and diurnal state simulation to AI agents.
//
// Zero external npm dependencies: runs on Node.js native ESM and stdio JSON-RPC.

import readline from 'node:readline';
import { getKittenState, interactKitten, getKittenPromptSummary } from './kitten-service.js';

const TOOLS = [
  {
    name: 'kitten_interact',
    description: 'Interact with your autonomous kitten companion. The kitten does NOT speak human language (only realistic meows, purrs, and feline body language) and has full diurnal autonomy (exploring, hiding, zoomies, stepping on your head).',
    inputSchema: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['look', 'search', 'pet', 'play', 'feed', 'snuggle', 'step_on_head', 'rename'],
          description: 'Action to perform: look (observe), search (find hiding spot), pet (chin scratches/purrs), play (toss paper ball/toy), feed (offer treat), snuggle (cuddle/nap), step_on_head (knead on head), rename (name the kitten).'
        },
        item: {
          type: 'string',
          description: 'Optional item to use when playing or feeding (e.g. "小纸团", "逗猫棒", "小鱼干", "冻干")'
        },
        name: {
          type: 'string',
          description: 'New name for the kitten (only used when action is "rename")'
        }
      },
      required: ['action']
    }
  },
  {
    name: 'kitten_status',
    description: 'Query the current location, mood, energy, affection, and prompt summary of your kitten companion.',
    inputSchema: {
      type: 'object',
      properties: {}
    }
  }
];

function handleToolCall(name, args = {}) {
  switch (name) {
    case 'kitten_interact':
    case 'qq_kitten_interact': {
      const res = interactKitten(args.action, { item: args.item, name: args.name });
      return { text: res.response };
    }
    case 'kitten_status': {
      const state = getKittenState();
      const promptLine = getKittenPromptSummary();
      return {
        text: `${promptLine}\n\n当前状态详情：\n- 名字: ${state.name}\n- 位置: ${state.location}\n- 行为: ${state.action}\n- 心情: ${state.mood}\n- 亲密度: ${state.affection}\n- 玩具库存: ${state.inventory.join(', ')}`
      };
    }
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

// JSON-RPC stdio protocol loop
const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false });

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
          serverInfo: { name: 'mcp-kitten-companion', version: '1.0.0' }
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
        const result = handleToolCall(toolName, toolArgs);
        const res = {
          jsonrpc: '2.0',
          id,
          result: {
            content: [{ type: 'text', text: result.text }]
          }
        };
        process.stdout.write(JSON.stringify(res) + '\n');
      } catch (err) {
        const res = {
          jsonrpc: '2.0',
          id,
          result: {
            content: [{ type: 'text', text: `Error: ${err?.message || err}` }],
            isError: true
          }
        };
        process.stdout.write(JSON.stringify(res) + '\n');
      }
    } else {
      process.stdout.write(JSON.stringify({
        jsonrpc: '2.0',
        id,
        error: { code: -32601, message: `Method not found: ${method}` }
      }) + '\n');
    }
  } catch (err) {
    process.stderr.write(`[mcp-kitten-companion] JSON parse error: ${err.message}\n`);
  }
});
