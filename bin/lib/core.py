# -*- coding: utf-8 -*-
"""ai-fish core primitives: paths, cross-platform lock, atomicity, state, and jsonl."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Cross-platform file locking support: Windows (msvcrt) vs POSIX (fcntl)
try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _detect_base() -> Path:
    env_base = os.environ.get("AI_FISH_BASE")
    if env_base:
        return Path(env_base).resolve()
    main_mod = sys.modules.get("__main__")
    if main_mod and hasattr(main_mod, "__file__") and main_mod.__file__:
        try:
            main_path = Path(main_mod.__file__).resolve()
            if main_path.name == "mem.py" and main_path.parent.name == "bin":
                return main_path.parent.parent
        except Exception:
            pass
    return Path(__file__).resolve().parents[2]


BASE = _detect_base()
WORKSPACE = BASE
DAILY = BASE / "daily"
RAW = DAILY / "raw"
ARCHIVE = DAILY / "archive"
INDEX = BASE / "index"
SNAPSHOTS = BASE / "snapshots"
CONFIG_PATH = BASE / "config.json"
STATE_PATH = BASE / "state.json"
PROCESSED_PATH = INDEX / "processed.jsonl"
EVENTS_INDEX = INDEX / "events.jsonl"
TODO_DONE_PATH = INDEX / "todo-done.jsonl"
RESUME_PATH = INDEX / "resume.md"
RESUME_MAX_CHARS = 1200
MANIFEST_PATH = SNAPSHOTS / "MANIFEST.jsonl"
RULES_MIRROR = BASE / "RULES.md"
LOCAL_SEAL = INDEX / "rules.sha256"
LOCK_PATH = INDEX / ".lock"
GRANTS_PATH = INDEX / "grants.jsonl"
DSH_HOME = Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh")))
SESSION_ROOT = DSH_HOME / "sessions"

DEFAULT_CONFIG = {
    "version": 1,
    "workspace": str(WORKSPACE),
    "canonical_rules": str(Path.home() / ".ai-fish" / "RULES.md"),
    "canonical_seal": str(Path.home() / ".ai-fish" / "RULES.sha256"),
    "max_note_chars": 12000,
    "max_search_results": 80,
}

KINDS = ("event", "statement", "observation", "inference", "unknown", "todo")
REQUIRED_SECTIONS = (
    "## 事件",
    "## 明确表达",
    "## 观察",
    "## 推断",
    "## 未知",
    "## 待办",
)
ALLOWED_SEAL_STATUS = ("OK", "MIRROR_MISMATCH")


class MemError(Exception):
    """A user-facing failure; never silently swallowed by the CLI."""


def now() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat(timespec="seconds")


def today_str() -> str:
    return now().date().isoformat()


def session_id() -> str:
    return (
        os.environ.get("AI_FISH_SESSION_ID")
        or os.environ.get("DSH_SESSION_ID")
        or "default-session"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return default
    except UnicodeDecodeError as exc:
        raise MemError(f"文件不是有效 UTF-8：{path} ({exc})") from exc


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[已截断，原长 {len(text)} 字符]"


def rel_posix(path: Path, base: Path = BASE) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


def ensure_dirs() -> None:
    for d in (BASE, DAILY, RAW, ARCHIVE, INDEX, SNAPSHOTS, BASE / "bin"):
        d.mkdir(parents=True, exist_ok=True)


@contextmanager
def memory_lock(timeout: float = 30.0):
    """Serialize memory mutations across processes/sessions.

    Cross-platform locking:
      - Windows: msvcrt.locking on index/.lock byte region
      - POSIX: fcntl.flock on index/.lock
    When the process terminates or exits the context, lock is reliably released.
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"L")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + timeout

        if msvcrt is not None:
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise MemError(
                            f"无法在 {timeout:.0f}s 内获取记忆写锁；另一个进程可能正在写入"
                        ) from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        elif fcntl is not None:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise MemError(
                            f"无法在 {timeout:.0f}s 内获取记忆写锁；另一个进程可能正在写入"
                        ) from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        else:
            yield


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception as exc:  # noqa: BLE001 - report and keep defaults
            print(f"WARN: 无法读取 config.json，使用默认配置：{exc}")
    # Standalone fallback: if canonical rules are not found at default home dir,
    # fallback to local repository RULES.md and RULES.sha256
    can_rules = Path(cfg["canonical_rules"])
    can_seal = Path(cfg["canonical_seal"])
    if not can_rules.is_file() and RULES_MIRROR.is_file():
        cfg["canonical_rules"] = str(RULES_MIRROR)
    if not can_seal.is_file():
        if (BASE / "RULES.sha256").is_file():
            cfg["canonical_seal"] = str(BASE / "RULES.sha256")
        elif LOCAL_SEAL.is_file():
            cfg["canonical_seal"] = str(LOCAL_SEAL)
    return cfg


def _clear_readonly(path: Path) -> None:
    if path.exists():
        try:
            os.chmod(path, path.stat().st_mode | stat.S_IWRITE)
        except OSError:
            pass


def atomic_write_bytes(path: Path, data: bytes, make_readonly: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _clear_readonly(path)
    tmp = path.parent / f".tmp-{path.name}-{secrets.token_hex(4)}"
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    if make_readonly:
        try:
            os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass


def atomic_write(path: Path, text: str, make_readonly: bool = False) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), make_readonly=make_readonly)


def atomic_write_text(path: Path, text: str, make_readonly: bool = False) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), make_readonly=make_readonly)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def read_jsonl(path: Path) -> tuple[list[dict], list[tuple[int, str]]]:
    if not path.exists():
        return [], []
    records: list[dict] = []
    bad_lines: list[tuple[int, str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    records.append(obj)
                else:
                    bad_lines.append((idx, line))
            except json.JSONDecodeError:
                bad_lines.append((idx, line))
    return records, bad_lines


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "version": 1,
            "createdAt": iso(),
            "lastSession": None,
            "lastConsolidation": None,
            "lastNoteAt": None,
            "lastSnapshotAt": None,
        }
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise MemError(f"state.json 无法解析：{exc}") from exc
    if not isinstance(data, dict):
        raise MemError("state.json 不是 JSON 对象")
    data.setdefault("version", 1)
    data.setdefault("lastSession", None)
    data.setdefault("lastConsolidation", None)
    data.setdefault("lastNoteAt", None)
    data.setdefault("lastSnapshotAt", None)
    return data


def save_state(state: dict) -> None:
    atomic_write_text(STATE_PATH, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
