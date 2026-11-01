# -*- coding: utf-8 -*-
"""ai-fish full-text search across long-term files, dailies, and raw events."""
from __future__ import annotations

import argparse
from pathlib import Path

from .core import BASE, DAILY, WORKSPACE, MemError, ensure_dirs, load_config, read_text, rel_posix
from .storage import all_raw_events


def _search_text(query: str, limit: int) -> list[tuple[str, int | str, str]]:
    terms = [t.casefold() for t in query.split() if t]
    results: list[tuple[str, int | str, str]] = []
    cfg = load_config()

    files = [
        BASE / "RULES.md",
        BASE / "SELF.md",
        BASE / "USER.md",
        BASE / "MEMORY.md",
        WORKSPACE / "AGENTS.md",
        Path(cfg.get("canonical_rules", "")),
    ]
    files += sorted(DAILY.glob("20??-??-??.md"))
    seen_files = set()
    for path in files:
        if not path.is_file():
            continue
        path_key = str(path.resolve()).casefold()
        if path_key in seen_files:
            continue
        seen_files.add(path_key)
        try:
            text = read_text(path)
        except MemError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            folded = line.casefold()
            if all(term in folded for term in terms):
                results.append((rel_posix(path), lineno, line.strip()[:300]))

    events, _ = all_raw_events()
    for path, lineno, obj in events:
        hay = " ".join(
            str(obj.get(k, "")) for k in ("id", "kind", "text", "ref", "tags")
        ).casefold()
        if all(term in hay for term in terms):
            preview = str(obj.get("text", "")).replace("\n", " ")[:240]
            results.append(
                (rel_posix(path), lineno, f"[{obj.get('id')}] {obj.get('kind')}: {preview}")
            )

    results.sort(key=lambda item: (item[0], item[1] if isinstance(item[1], int) else 999999))
    return results


def cmd_search(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_dirs()
    if not args.query.strip():
        raise MemError("查询为空")
    limit = args.limit or int(cfg.get("max_search_results", 80))

    use_text_only = getattr(args, "text_only", False)
    if not use_text_only:
        try:
            from .db import get_db_path, search_fts
            if get_db_path().is_file():
                fts_rows = search_fts(args.query, limit=limit)
                if fts_rows:
                    print(f"SEARCH \"{args.query}\" (FTS5) -> {len(fts_rows)} hit(s)")
                    for r in fts_rows[:limit]:
                        snippet = r["body"][:120].replace("\n", " ")
                        title = f" [{r['title']}]" if r["title"] else ""
                        print(f"{r['doc']}:{r['item_id']}: [{r['category']}]{title} {snippet}")
                    if len(fts_rows) > limit:
                        print(f"... 还有 {len(fts_rows) - limit} 条，未显示。")
                    return 0
        except Exception:
            pass  # Fall back to text search on any DB failure

    results = _search_text(args.query, limit)
    print(f"SEARCH \"{args.query}\" -> {len(results)} hit(s)")
    for path, lineno, line in results[:limit]:
        print(f"{path}:{lineno}: {line}")
    if len(results) > limit:
        print(f"... 还有 {len(results) - limit} 条，未显示。")
    if not results:
        print("NO_MATCHES")
    return 0
