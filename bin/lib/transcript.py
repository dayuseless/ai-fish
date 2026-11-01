# -*- coding: utf-8 -*-
"""ai-fish transcript: read-only DSH session frame decoding and summarization."""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .core import SESSION_ROOT, WORKSPACE, MemError, session_id

try:
    from compression.zstd import ZstdDecompressor, get_frame_size

    _ZSTD_IMPORT_ERROR: Exception | None = None
except ImportError as _exc:  # Python < 3.14
    ZstdDecompressor = None  # type: ignore[assignment]
    get_frame_size = None  # type: ignore[assignment]
    _ZSTD_IMPORT_ERROR = _exc

_SECRET_PATTERNS = (
    (re.compile(r"(?i)sk-[A-Za-z0-9_-]{8,}"), "sk-***"),
    (
        re.compile(
            r"(?i)((?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*)(\S+)"
        ),
        r"\1***",
    ),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)(\S+)"), r"\1***"),
)


def _zstd_ready() -> None:
    if _ZSTD_IMPORT_ERROR is not None:
        raise MemError(
            "当前 Python 缺少 compression.zstd（需要 Python 3.14+）："
            f"{_ZSTD_IMPORT_ERROR}"
        )


def _fmt_ms(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "--:--:--"


def _redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                value = item.get("text")
                if value:
                    parts.append(str(value))
    return "\n".join(parts)


def _read_session_frames(path: Path):
    """Decode concatenated zstd frames written by DSH's append-only session log."""
    _zstd_ready()
    data = path.read_bytes()
    chunks: list[bytes] = []
    pos = 0
    frames = 0
    truncated = False
    while pos < len(data):
        try:
            size = get_frame_size(data[pos:])
        except Exception:  # noqa: BLE001 - a growing/partial tail is expected
            truncated = True
            break
        if size <= 0:
            truncated = True
            break
        try:
            chunks.append(ZstdDecompressor().decompress(data[pos : pos + size]))
        except Exception:  # noqa: BLE001
            truncated = True
            break
        pos += size
        frames += 1
    return b"".join(chunks), frames, truncated


def _session_files() -> list[Path]:
    if not SESSION_ROOT.is_dir():
        return []
    return sorted(
        SESSION_ROOT.rglob("session.v4.jsonl.zstd"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _read_first_frame(path: Path) -> bytes:
    """Read only the session header frame; fall back to a full decode if needed."""
    _zstd_ready()
    with path.open("rb") as f:
        head = f.read(65536)
    if not head:
        return b""
    try:
        size = get_frame_size(head)
        if size > 0 and size <= len(head):
            return ZstdDecompressor().decompress(head[:size])
    except Exception:  # noqa: BLE001
        pass
    raw, _, _ = _read_session_frames(path)
    return raw.split(b"\n", 1)[0] if raw else b""


def _session_header(path: Path) -> dict:
    try:
        raw = _read_first_frame(path)
        first = raw.split(b"\n", 1)[0]
        obj = json.loads(first.decode("utf-8", "replace"))
        return obj if isinstance(obj, dict) else {}
    except Exception:  # noqa: BLE001 - header is informational only
        return {}


def _same_workspace(path: Path) -> bool:
    cwd = _session_header(path).get("cwd")
    if not cwd:
        return False
    try:
        return os.path.normcase(os.path.abspath(str(cwd))) == os.path.normcase(
            os.path.abspath(str(WORKSPACE))
        )
    except OSError:
        return False


def _resolve_session(token: str, files: list[Path]) -> Path:
    token = (token or "current").strip()
    current = session_id()
    if token == "current":
        matches = [p for p in files if p.parent.name == current]
        if matches:
            return matches[0]
        same = [p for p in files if _same_workspace(p)]
        if same:
            return same[0]
        raise MemError("找不到当前工作区的 DSH 会话记录")
    if token == "previous":
        same = [p for p in files if p.parent.name != current and _same_workspace(p)]
        if same:
            return same[0]
        raise MemError(
            "同一工作区没有其他 DSH 会话记录可作为 previous；"
            "用 --list 查看全部，或用 --session <id> 指定"
        )
    exact = [p for p in files if p.parent.name == token]
    if exact:
        return exact[0]
    prefix = [
        p
        for p in files
        if p.parent.name.startswith(token) or p.parent.name.startswith(f"session-{token}")
    ]
    if prefix:
        return prefix[0]
    raise MemError(f"找不到会话：{token}；先用 `mem.py transcript --list` 查看")


def _row_digest(row: dict):
    typ = row.get("type")
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    if typ == "user/message":
        text = _content_text(data.get("content"))
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        label = "user"
        if (
            source.get("kind") == "runtime-context"
            or text.startswith("Current runtime context")
            or text.startswith("Time sampled while preparing")
            or text.startswith("Elapsed since")
        ):
            label = "runtime"
        elif text.lstrip().startswith("<goal_round>") or "Objective:" in text[:300]:
            label = "goal"
        elif "<system-reminder>" in text[:500]:
            label = "instruction"
        return label, text
    if typ == "assistant/message":
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        return "assistant", _content_text(message.get("content"))
    if typ == "tool/call":
        name = data.get("name") or "?"
        args = data.get("arguments") or ""
        return "tool", f"{name} {args}"
    if typ == "tool/result":
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        text = _content_text(message.get("content"))
        prefix = "ERROR " if message.get("isError") else ""
        return "result", prefix + text
    if typ == "approval/decided":
        return "approval", str(data.get("outcome"))
    if typ == "goal/change":
        return "goal-change", str(data.get("operation"))
    return None


def cmd_transcript(args: argparse.Namespace) -> int:
    _zstd_ready()
    files = _session_files()
    if args.list:
        print("DSH sessions:  (* current, + same workspace)")
        if not files:
            print("  (none)")
        for path in files:
            header = _session_header(path)
            if path.parent.name == session_id():
                marker = "*"
            elif _same_workspace(path):
                marker = "+"
            else:
                marker = " "
            print(f"{marker} {path.parent.name}")
            print(f"    cwd={header.get('cwd')} created={_fmt_ms(header.get('createdAt'))} size={path.stat().st_size} B")
            print(f"    file={path}")
        return 0

    if args.max_chars <= 0 or args.max_item_chars <= 0:
        raise MemError("--max-chars 与 --max-item-chars 必须大于 0")

    path = _resolve_session(args.session, files)
    raw, frames, truncated = _read_session_frames(path)
    rows: list[dict] = []
    bad = 0
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)

    items: list[tuple[object, object, str, str]] = []
    for row in rows:
        parsed = _row_digest(row)
        if not parsed:
            continue
        label, text = parsed
        text = _redact(text or "")
        if not text.strip():
            continue
        if label in ("runtime", "instruction", "goal") and not args.include_context:
            continue
        if label in ("tool", "result") and not args.include_tools:
            continue
        items.append((row.get("seq"), row.get("time"), label, text))

    print(f"SESSION {path.parent.name}")
    print(f"  file={path}")
    print(f"  frames={frames} rows={len(rows)} bad_lines={bad} truncated={truncated}")
    counts = Counter(label for _, _, label, _ in items)
    print("  digest_items=" + ", ".join(f"{k}={v}" for k, v in counts.most_common()))
    print("  NOTE: 只读摘要，未复制进记忆库；完整原始记录仍在上面的文件。")
    print()

    used = 0
    shown = 0
    for _seq, ms, label, text in items:
        text = re.sub(r"\s+", " ", text).strip()
        if label == "goal":
            text = text[:300]
        if len(text) > args.max_item_chars:
            text = text[: args.max_item_chars] + "…"
        line = f"[{_fmt_ms(ms)}] {label}: {text}"
        if used + len(line) + 1 > args.max_chars:
            print(f"... (budget {args.max_chars} chars reached; {len(items) - shown} items not shown)")
            break
        print(line)
        used += len(line) + 1
        shown += 1
    if not items:
        print("NO_DIGEST_ITEMS (试试 --include-context 或 --include-tools)")
    return 0
