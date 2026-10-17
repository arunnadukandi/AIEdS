"""
load_test.py — Find the safe concurrent-user ceiling for AIEdS chatbot
========================================================================
Isolates the two components that actually break under concurrent load —
Ollama inference and SQLite writes — without needing a browser-automation
rig to drive Streamlit itself. Streamlit's own session handling scales
fine; these two are the real bottlenecks.

Usage:
    python load_test.py ollama --levels 1,2,4,8,16 --reps 3
    python load_test.py sqlite --levels 1,4,16,32 --writes 20
    python load_test.py both

Requires: pip install ollama    (psutil optional, for CPU/RAM readout)
"""
import argparse
import os
import sqlite3
import statistics
import tempfile
import threading
import time

OLLAMA_HOST  = "http://127.0.0.1:11434"
OLLAMA_MODEL = "llama3.2:3b-instruct-q4_K_M"

# A realistic-length cadet question, similar to what chatbot.py sends
# (short system prompt + retrieved context + question).
SAMPLE_MESSAGES = [
    {"role": "system", "content": "You are a naval academy instructor assistant. "
                                   "Answer using only the provided context."},
    {"role": "user", "content": (
        "Context: A gyrocompass uses a fast-spinning rotor and gravity control "
        "to seek true north, unaffected by magnetic interference, unlike a "
        "magnetic compass.\n\n"
        "Question: Explain the basic working principle of a gyrocompass and "
        "why it is preferred over a magnetic compass aboard a warship."
    )},
]


def _resource_snapshot() -> str:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory().percent
        return f"CPU {cpu:5.1f}%  RAM {mem:5.1f}%"
    except ImportError:
        return "(install psutil for CPU/RAM readout: pip install psutil)"


# ── Ollama inference load test ──────────────────────────────────────────────

def _one_ollama_call(client, results: list, idx: int):
    t0 = time.time()
    try:
        resp = client.chat(
            model=OLLAMA_MODEL,
            messages=SAMPLE_MESSAGES,
            stream=False,
            options={"num_gpu": 50, "temperature": 0.0, "num_ctx": 2048},
        )
        elapsed = time.time() - t0
        ok = bool(resp.get("message", {}).get("content"))
        results[idx] = (ok, elapsed, None)
    except Exception as e:
        results[idx] = (False, time.time() - t0, str(e))


def run_ollama_test(levels: list, reps: int):
    from ollama import Client
    from httpx import Timeout
    client = Client(host=OLLAMA_HOST, timeout=Timeout(120.0))

    print(f"\n=== Ollama inference load test — model={OLLAMA_MODEL} ===")
    print("Each 'level' = that many chat requests fired at the same instant.\n")

    summary = []
    for level in levels:
        rep_latencies = []
        rep_errors = 0
        for rep in range(reps):
            results = [None] * level
            threads = [
                threading.Thread(target=_one_ollama_call, args=(client, results, i))
                for i in range(level)
            ]
            t_start = time.time()
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            batch_wall = time.time() - t_start

            oks = [r for r in results if r[0]]
            errs = [r for r in results if not r[0]]
            rep_errors += len(errs)
            if oks:
                rep_latencies.extend(r[1] for r in oks)

            print(f"  level={level:>3} rep={rep+1}/{reps}  "
                  f"wall={batch_wall:6.1f}s  ok={len(oks)}/{level}  "
                  f"avg_latency={statistics.mean(r[1] for r in oks):6.1f}s"
                  if oks else
                  f"  level={level:>3} rep={rep+1}/{reps}  ALL FAILED")
            if errs:
                print(f"      sample error: {errs[0][2]}")
            print(f"      {_resource_snapshot()}")

        if rep_latencies:
            summary.append((level, statistics.mean(rep_latencies),
                             max(rep_latencies), rep_errors))
        else:
            summary.append((level, None, None, rep_errors))

    print("\n--- Summary ---")
    print(f"{'Concurrency':>11} | {'Avg latency':>11} | {'Max latency':>11} | {'Errors':>6}")
    for level, avg, mx, errs in summary:
        avg_s = f"{avg:.1f}s" if avg is not None else "  n/a"
        mx_s = f"{mx:.1f}s" if mx is not None else "  n/a"
        print(f"{level:>11} | {avg_s:>11} | {mx_s:>11} | {errs:>6}")
    print(
        "\nRead it as: single-request latency is your floor. The concurrency "
        "level where avg latency roughly doubles (or errors appear) is your "
        "practical ceiling — past that point, requests are queuing behind "
        "each other rather than running in parallel. Ollama's timeout in "
        "llm_client.py / chatbot.py is 120s, so any avg latency approaching "
        "that means cadets will start seeing failures, not just slowness."
    )


# ── SQLite concurrent-write test ────────────────────────────────────────────

def _init_test_db(path: str):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback_sim (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT, feedback INTEGER, ts TEXT
        )
    """)
    conn.commit()
    conn.close()


def _one_sqlite_writer(path: str, writes: int, results: list, idx: int):
    errors = 0
    t0 = time.time()
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        for i in range(writes):
            conn.execute(
                "INSERT INTO feedback_sim (query, feedback, ts) VALUES (?, ?, datetime('now'))",
                (f"sim query {idx}-{i}", 1),
            )
            conn.commit()
        conn.close()
    except Exception as e:
        errors += 1
        results[idx] = (False, time.time() - t0, str(e))
        return
    results[idx] = (True, time.time() - t0, None)


def run_sqlite_test(levels: list, writes: int):
    print(f"\n=== SQLite concurrent-write test — {writes} writes per thread ===")
    print("Simulates many cadets submitting feedback/session writes at once.\n")

    tmp_dir = tempfile.mkdtemp(prefix="aieds_sqlite_test_")
    summary = []
    for level in levels:
        db_path = os.path.join(tmp_dir, f"test_{level}.db")
        _init_test_db(db_path)
        results = [None] * level
        threads = [
            threading.Thread(target=_one_sqlite_writer, args=(db_path, writes, results, i))
            for i in range(level)
        ]
        t_start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.time() - t_start

        oks = [r for r in results if r[0]]
        errs = [r for r in results if not r[0]]
        print(f"  writers={level:>3}  wall={wall:6.1f}s  ok={len(oks)}/{level}")
        if errs:
            print(f"      sample error: {errs[0][2]}")
        summary.append((level, wall, len(errs)))

    print("\n--- Summary ---")
    print(f"{'Writers':>8} | {'Wall time':>10} | {'Errors':>6}")
    for level, wall, errs in summary:
        flag = "  <-- 'database is locked' errors appearing" if errs else ""
        print(f"{level:>8} | {wall:>9.1f}s | {errs:>6}{flag}")
    print(
        "\nIf errors appear at realistic concurrency levels, switch sahayak.db "
        "to WAL mode (conn.execute('PRAGMA journal_mode=WAL')) and add a "
        "busy_timeout — this alone usually fixes SQLite contention without "
        "needing to cap users for this reason specifically."
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("test", choices=["ollama", "sqlite", "both"])
    p.add_argument("--levels", default="1,2,4,8",
                    help="Comma-separated concurrency levels to test, e.g. 1,2,4,8,16")
    p.add_argument("--reps", type=int, default=2,
                    help="Repetitions per level for the ollama test (default 2)")
    p.add_argument("--writes", type=int, default=20,
                    help="Writes per thread for the sqlite test (default 20)")
    args = p.parse_args()
    levels = [int(x) for x in args.levels.split(",")]

    if args.test in ("ollama", "both"):
        run_ollama_test(levels, args.reps)
    if args.test in ("sqlite", "both"):
        run_sqlite_test(levels, args.writes)
