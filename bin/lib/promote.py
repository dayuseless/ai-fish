# -*- coding: utf-8 -*-
"""ai-fish long-term memory promotion candidates detection."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta

from .core import BASE, DAILY, ensure_dirs, now, read_text

_PROMOTE_KEYWORDS = ("已完成", "部署", "上线", "修复", "新增", "启用", "确认", "通过")


def cmd_promote_check(args: argparse.Namespace) -> int:
    """扫描近期日记，检测可能应该升格到长期记忆但尚未出现的候选条目。

    检查维度：
    1. MEMORY/USER/SELF 最后更新日期是否滞后
    2. 日记中的高/中置信推断、用户明确表达、重要事件是否已在长期记忆中
    """
    ensure_dirs()
    days = max(1, int(args.days))
    cutoff = (now() - timedelta(days=days)).date().isoformat()

    daily_files = sorted(DAILY.glob("20??-??-??.md"))
    recent = [p for p in daily_files if p.stem >= cutoff]

    if not recent:
        print(f"PROMOTE_CHECK: 近 {days} 天无日记")
        return 0

    long_files: dict[str, str] = {}
    for name in ("MEMORY.md", "USER.md", "SELF.md"):
        long_files[name] = read_text(BASE / name)
    long_text_lower = "\n".join(long_files.values()).casefold()

    stale: list[str] = []
    for name, text in long_files.items():
        m = re.search(r"最后更新：(\d{4}-\d{2}-\d{2})", text)
        if m:
            last = m.group(1)
            try:
                age = (now().date() - datetime.strptime(last, "%Y-%m-%d").date()).days
            except ValueError:
                age = 0
            if age > 2:
                stale.append(f"{name} 已 {age} 天未更新（最后更新：{last}）")

    candidates: list[dict] = []

    for path in recent:
        text = read_text(path)
        lines = text.splitlines()
        current_section = ""
        current_batch = ""
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r"^##\s+固化批次\s+(\S+)", line)
            if m:
                current_batch = m.group(1)
                i += 1
                continue
            if line.startswith("## "):
                current_section = line[3:].strip()
                i += 1
                continue

            if line.startswith("- ") and current_section in ("推断", "明确表达", "事件"):
                content = line[2:].strip()
                while (
                    i + 1 < len(lines)
                    and not lines[i + 1].strip().startswith("## ")
                    and not lines[i + 1].strip().startswith("# ")
                    and not lines[i + 1].strip().startswith("- ")
                    and lines[i + 1].strip()
                ):
                    i += 1
                    content += " " + lines[i].strip()

                is_candidate = False
                reason = ""
                if current_section == "推断" and ("高置信" in content or "中置信" in content):
                    is_candidate = True
                    conf = "高置信" if "高置信" in content else "中置信"
                    reason = f"推断（{conf}）"
                elif current_section == "明确表达" and len(content) > 30:
                    is_candidate = True
                    reason = "用户明确表达"
                elif current_section == "事件" and any(kw in content for kw in _PROMOTE_KEYWORDS):
                    is_candidate = True
                    reason = "重要事件/里程碑"

                if is_candidate:
                    key_phrases = [
                        w for w in re.split(r"[，。、：；（）「」\s*]+", content)
                        if len(w) >= 4
                    ]
                    already = any(
                        p.casefold() in long_text_lower for p in key_phrases[:5]
                    ) if key_phrases else False

                    if not already:
                        candidates.append({
                            "file": path.name,
                            "batch": current_batch[:16] if current_batch else path.stem,
                            "section": current_section,
                            "reason": reason,
                            "text": content[:200],
                        })
            i += 1

    if args.json:
        print(
            json.dumps(
                {"stale": stale, "candidates": candidates},
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0

    print(f"PROMOTE_CHECK 近 {days} 天 · 扫描 {len(recent)} 篇日记")

    if stale:
        for s in stale:
            print(f"STALE: {s}")
    else:
        print("长期记忆文件更新日期正常")

    if candidates:
        print(f"\nCANDIDATES: {len(candidates)} 条未在长期记忆中出现的候选项")
        for idx, c in enumerate(candidates[:30], 1):
            print(f"  {idx:>2}. [{c['file']} {c['batch']}] {c['reason']}")
            print(f"      {c['text'][:150]}")
    else:
        print("\nNO_CANDIDATES: 近期日记中的重要条目均已覆盖")

    return 0
