# MEMORY.md — 长期记忆索引

- 版本：1.0
- 作用：保存对跨会话延续性有实际帮助的高阶认识、系统事实与检索索引。过程细节保存在日记中。

---

## 1. 运行环境与基础设施

- **环境**：支持 Windows / macOS / Linux；Python 3.10+。
- **架构**：ai-fish 纯文本权威底座 + SQLite 双轨加速。

## 2. 记忆系统结构

- **权威规则**：`RULES.md`（SHA-256 封印校验，变更可见）
- **路由入口**：`META.md`（元文档 ≤ 6 KB，按需触发索引）
- **细则指南**：`SPEC.md`（详细操作规范）
- **核心文档**：`SELF.md`、`USER.md`、`MEMORY.md`（修改前必须快照）
- **原始事件流**：`daily/raw/YYYY-MM-DD.jsonl`（纯文本 Append-Only）
- **每日日记**：`daily/YYYY-MM-DD.md`（六段式结构化摘要）
- **轻量数据库**：`index/memory.db`（SQLite 双轨加速，FTS5 全文索引）
- **待办账本**：`index/todo-done.jsonl`（已办任务过滤账本）
- **快照灾备**：`snapshots/`（修改前自动快照留痕）

## 3. 事项状态

- **M-001｜记忆系统初始化**：完成记忆库建立与封印校验通过。
