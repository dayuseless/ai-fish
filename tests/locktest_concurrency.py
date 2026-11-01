import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent  # ai-fish
ROOT = HERE / "locktest"
CLI = ROOT / "bin" / "mem.py"
N = 8


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


# Build a disposable copy so the concurrency test never touches real memory.
force_rmtree(ROOT)
(ROOT / "bin").mkdir(parents=True)
shutil.copyfile(SOURCE / "bin" / "mem.py", CLI)
shutil.copytree(SOURCE / "bin" / "lib", ROOT / "bin" / "lib", dirs_exist_ok=True)
shutil.copyfile(SOURCE / "RULES.md", ROOT / "RULES.md")

env = os.environ.copy()
env["PYTHONUTF8"] = "1"
procs = []
for i in range(N):
    cmd = [
        sys.executable,
        "-X",
        "utf8",
        str(CLI),
        "note",
        "--kind",
        "event",
        "--text",
        f"concurrency-{i}",
        "--ref",
        "locktest",
    ]
    procs.append(
        subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    )
rcs = [p.wait() for p in procs]
print("RC", rcs)

raw_files = sorted((ROOT / "daily" / "raw").glob("*.jsonl"))
if len(raw_files) != 1:
    print("BAD_RAW_FILES", [str(p) for p in raw_files])
    sys.exit(1)
raw_lines = [ln for ln in raw_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
raw = [json.loads(ln) for ln in raw_lines]
ids = [r["id"] for r in raw]
print("RAW_LINES", len(raw), "UNIQUE_IDS", len(set(ids)))

index_lines = [ln for ln in (ROOT / "index" / "events.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
index = [json.loads(ln) for ln in index_lines]
line_numbers = sorted(r["line"] for r in index)
print("INDEX_LINES", len(index), "LINE_NUMBERS", line_numbers)
print("LOCK_BYTES", (ROOT / "index" / ".lock").stat().st_size)

ok = True
if any(rc != 0 for rc in rcs):
    ok = False
if len(raw) != N or len(set(ids)) != N:
    ok = False
if len(index) != N or line_numbers != list(range(1, N + 1)):
    ok = False
if not (ROOT / "state.json").is_file():
    ok = False
else:
    json.loads((ROOT / "state.json").read_text(encoding="utf-8"))
print("CONCURRENCY_PASS" if ok else "CONCURRENCY_FAIL")
if ok and "--keep" not in sys.argv:
    force_rmtree(ROOT)
else:
    print("ARTIFACTS", ROOT)
sys.exit(0 if ok else 1)
