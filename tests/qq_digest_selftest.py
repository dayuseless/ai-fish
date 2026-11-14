"""Self-test for bin/qq-digest.py.

用临时目录里的 social-v2.json 夹具跑「采集 → 幂等 → 增量」三步，
不读也不写真实的 D:\\qq-bridge 和 ai-fish/inbox。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
TOOL = BASE / "bin" / "qq-digest.py"


def msg(seq, mid, sender, text, ts, is_self=False):
    return {
        "seq": seq,
        "messageId": mid,
        "sender": sender,
        "userId": "1" if not is_self else None,
        "text": text,
        "isSelf": is_self,
        "time": ts,
    }


def run(env, *args):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="qq-digest-test-") as tmp:
        root = Path(tmp)
        bridge = root / "bridge"
        (bridge / "state").mkdir(parents=True)
        social = bridge / "state" / "social-v2.json"
        fixture = {
            "conversations": {
                "private:42": {
                    "recentMessages": [
                        msg(1, "a1", "私聊", "你好", 1000),
                        msg(None, None, "我", "在的", 2000, is_self=True),
                        msg(2, "a2", "私聊", "帮我看个东西", 3000),
                    ],
                    "activeTopics": [{"text": "测试话题"}],
                    "memberImpressions": {"私聊": {"traits": ["直"]}},
                }
            }
        }
        social.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")

        env = dict(os.environ)
        env["QQ_BRIDGE_DIR"] = str(bridge)
        env["QQ_DIGEST_STATE"] = str(root / "state.json")
        env["QQ_DIGEST_INBOX"] = str(root / "inbox")

        st = run(env, "status")
        assert st.returncode == 0, st.stderr
        assert "3 条新消息" in st.stdout, st.stdout

        cap = run(env, "capture")
        assert cap.returncode == 0, cap.stderr
        assert "CAPTURE_OK" in cap.stdout, cap.stdout
        files = list((root / "inbox").glob("qq-*.md"))
        assert len(files) == 1, files
        body = files[0].read_text(encoding="utf-8")
        for needle in ("你好", "在的", "帮我看个东西", "测试话题", "（self）"):
            assert needle in body, f"inbox missing: {needle}"

        # 幂等：同样的数据第二次不应重复采集
        again = run(env, "capture")
        assert "NO_NEW_MESSAGES" in again.stdout, again.stdout

        # 增量：夹具里追加一条新消息
        fixture["conversations"]["private:42"]["recentMessages"].append(
            msg(3, "a3", "私聊", "又来了", 4000)
        )
        social.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        inc = run(env, "capture")
        assert "messages=1" in inc.stdout, inc.stdout
        assert len(list((root / "inbox").glob("qq-*.md"))) == 2

        pend = run(env, "status")
        assert "待提炼 inbox 文件：2 个" in pend.stdout, pend.stdout

    print("PASS qq-digest: status/capture/idempotent/incremental")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
