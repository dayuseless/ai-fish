import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent  # ai-fish
ROOT = HERE / "faulttest"
CLI = ROOT / "bin" / "mem.py"
AGENTS = HERE / "AGENTS.md"
CREATED_AGENTS = False
FAILS = 0


def force_rmtree(path: Path) -> None:
    if not path.exists():
        return
    for item in path.rglob("*"):
        try:
            os.chmod(item, stat.S_IWRITE)
        except OSError:
            pass
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


def run(label: str, args: list[str]):
    out = HERE / f".{label}.txt"
    with out.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(CLI), *args],
            cwd=str(ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    text = out.read_text(encoding="utf-8", errors="replace")
    out.unlink(missing_ok=True)
    return proc.returncode, text


def run_separate(label: str, args: list[str]):
    out = HERE / f".{label}.out.txt"
    err = HERE / f".{label}.err.txt"
    with out.open("w", encoding="utf-8") as o, err.open("w", encoding="utf-8") as e:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(CLI), *args],
            cwd=str(ROOT),
            stdout=o,
            stderr=e,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    out_text = out.read_text(encoding="utf-8", errors="replace")
    err_text = err.read_text(encoding="utf-8", errors="replace")
    out.unlink(missing_ok=True)
    err.unlink(missing_ok=True)
    return proc.returncode, out_text, err_text


def expect(label: str, args: list[str], rc: int, must: tuple[str, ...] = ()) -> str:
    global FAILS
    code, text = run(label, args)
    ok = code == rc and all(part in text for part in must)
    print(f"{label}: rc={code} expected={rc} ok={ok}")
    if not ok:
        FAILS += 1
        print(text[-3000:])
    return text


force_rmtree(ROOT)
(ROOT / "bin").mkdir(parents=True)
for name in ("RULES.md", "SELF.md", "USER.md", "MEMORY.md", "META.md", "SPEC.md", "config.json", "state.json"):
    shutil.copyfile(SOURCE / name, ROOT / name)
shutil.copyfile(SOURCE / "bin" / "mem.py", CLI)
shutil.copytree(SOURCE / "bin" / "lib", ROOT / "bin" / "lib", dirs_exist_ok=True)
for name in ("daily", "index", "snapshots"):
    shutil.copytree(SOURCE / name, ROOT / name)

if not AGENTS.exists():
    AGENTS.write_text("# faulttest workspace\n", encoding="utf-8")
    CREATED_AGENTS = True

expect("baseline-verify", ["verify"], 0, ("VERIFY PASS",))

snap_text = expect("state-snapshot", ["snapshot", "--file", "state.json", "--note", "faulttest"], 0, ("SNAPSHOT_OK",))
snap_path = ""
for line in snap_text.splitlines():
    if line.startswith("SNAPSHOT_OK "):
        snap_path = line.split(" ", 1)[1].strip()
        break
if not snap_path:
    print("NO_SNAPSHOT_PATH")
    FAILS += 1

(ROOT / "state.json").write_text("{ this is not valid json", encoding="utf-8")
expect("corrupt-state-verify", ["verify"], 1, ("state.json 可解析",))
expect("corrupt-state-start", ["session-start"], 0, ("WARN", "state"))

def raw_lines_total() -> int:
    """所有 raw 文件的非空行总数（不写死日期，跨天也能测）。"""
    return sum(
        len([ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()])
        for path in (ROOT / "daily" / "raw").glob("*.jsonl")
    )


before = raw_lines_total()
expect("note-with-corrupt-state", ["note", "--kind", "event", "--text", "faulttest note", "--ref", "faulttest"], 0, ("WARN", "state 更新失败"))
after = raw_lines_total()
print("note_appended", after > before)
if after <= before:
    FAILS += 1

if snap_path:
    expect("state-restore", ["restore", "--snapshot", snap_path, "--yes"], 0, ("RESTORE_OK",))
    expect("verify-after-restore", ["verify"], 0, ("VERIFY PASS",))

raw = max((ROOT / "daily" / "raw").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
with raw.open("a", encoding="utf-8") as handle:
    handle.write('{"broken":\n')
expect("corrupt-raw-verify", ["verify"], 1, ("原始事件 JSONL 可解析",))
expect("corrupt-raw-start", ["session-start"], 0, ("WARN", "原始事件解析错误"))
expect("corrupt-raw-pending", ["pending"], 0, ("WARN", "原始事件解析错误"))
json_code, json_out, json_err = run_separate("corrupt-raw-json", ["pending", "--json"])
try:
    json_data = json.loads(json_out)
    json_ok = isinstance(json_data, list)
except json.JSONDecodeError:
    json_ok = False
json_warn = "原始事件解析错误" in json_err
print(f"corrupt-raw-json: rc={json_code} json_ok={json_ok} stderr_warn={json_warn}")
if json_code != 0 or not json_ok or not json_warn:
    FAILS += 1
    print("STDOUT:", json_out[-1000:])
    print("STDERR:", json_err[-1000:])

snaps = sorted((ROOT / "snapshots").rglob("*.bak"))
if snaps:
    snaps[0].unlink()
    expect("missing-snapshot-verify", ["verify"], 1, ("快照文件完整",))
else:
    print("NO_SNAPSHOT_TO_DELETE")
    FAILS += 1

if CREATED_AGENTS:
    AGENTS.unlink(missing_ok=True)
if FAILS == 0:
    force_rmtree(ROOT)
    print("FAULTTEST_PASS")
    sys.exit(0)
print("FAULTTEST_FAIL", "artifacts:", ROOT)
sys.exit(1)
