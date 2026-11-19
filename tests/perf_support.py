"""Shared helpers for the load / stress tests: data setup, running Locust, reading its results."""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import config
from helpers import connect, rows, run, run_sql_file, scalar

PERF_DIR = Path(__file__).resolve().parent / "perf"
OUT_DIR = config.REPORTS_DIR / "perf"
LOAD_USERS = 50
START_BALANCE = "1000000.00"

# Thresholds. Deliberately generous so they pass on a student laptop AND a shared CI runner,
# while still catching a real regression (a missing index, a lock that serialises everything).
READ_P95_MS = 1500
MONEY_P95_MS = 2000
LOGIN_P95_MS = 4000
MIN_REQUESTS_PER_SECOND = 30


def reseed(conn):
    """Empty every table and reload seed.sql (the same starting point every other test file gets)."""
    run(conn, "SET FOREIGN_KEY_CHECKS = 0")
    for table in ("audit_log", "loans", "transactions", "accounts", "users", "branches"):
        run(conn, f"TRUNCATE TABLE {table}")
    run(conn, "SET FOREIGN_KEY_CHECKS = 1")
    run_sql_file(conn, config.SEED_FILE)


def provision(conn, users=LOAD_USERS):
    """Reseed, then add `users` customers (load0..loadN-1), each with one account holding 1,000,000.00.
    Returns the total money in the system."""
    reseed(conn)
    pw_hash = scalar(conn, "SELECT password_hash FROM users WHERE user_id = 1")
    first_user = scalar(conn, "SELECT MAX(user_id) FROM users") + 1
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'customer')",
                        [(f"Load User {i}", f"load{i}@example.com", pw_hash) for i in range(users)])
        cur.executemany("INSERT INTO accounts (user_id, branch_id, balance, status) VALUES (%s, 1, %s, 'active')",
                        [(first_user + i, START_BALANCE) for i in range(users)])
    return scalar(conn, "SELECT SUM(balance) FROM accounts")


def run_locust(locustfile, classes=(), users=None, spawn_rate=None, seconds=None, tag="run", extra_env=None):
    """Run Locust headless against the test backend and return parsed results.
    Shape files (stress/spike) control users and duration themselves."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = OUT_DIR / tag
    for old in OUT_DIR.glob(f"{tag}_*"):
        old.unlink()
    env = os.environ.copy()
    env.update({"PERF_USERS": str(LOAD_USERS), "PERF_ACCOUNT_BASE": "3"})
    env.update(extra_env or {})
    cmd = [sys.executable, "-m", "locust", "-f", str(PERF_DIR / locustfile), "--headless",
           "--host", config.API_BASE_URL, "--csv", str(prefix), "--loglevel", "WARNING",
           "--only-summary", "--exit-code-on-error", "0", *classes]
    if users:
        cmd += ["-u", str(users), "-r", str(spawn_rate or users), "-t", f"{seconds}s"]
    proc = subprocess.run(cmd, cwd=PERF_DIR, env=env, capture_output=True, text=True, timeout=(seconds or 120) + 120)
    stats = _read_csv(f"{prefix}_stats.csv")
    if not stats:
        raise RuntimeError(f"Locust produced no results.\nSTDOUT:\n{proc.stdout[-1500:]}\nSTDERR:\n{proc.stderr[-1500:]}")
    return {
        "stats": {r["Name"]: r for r in stats},
        "failures": _read_csv(f"{prefix}_failures.csv"),
        "total": next(r for r in stats if r["Name"] == "Aggregated"),
        "stderr": proc.stderr,
    }


def _read_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def count(row, column="Request Count"):
    return int(float(row[column]))


def p95(row):
    return float(row["95%"])


def read_json_lines(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values, pct):
    values = sorted(values)
    if not values:
        return float("nan")
    k = min(len(values) - 1, max(0, round(pct / 100 * (len(values) - 1))))
    return values[k]


def ledger_problems(conn, money_at_start):
    """Reconcile the books after a load run. Returns (problems, open_db_transactions); problems is a list of
    human-readable strings, empty when everything adds up."""
    problems = []
    deposits = scalar(conn, "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='deposit' AND status='success'")
    withdrawals = scalar(conn, "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='withdrawal' AND status='success'")
    total = scalar(conn, "SELECT SUM(balance) FROM accounts")
    expected = money_at_start + deposits - withdrawals
    if total != expected:
        problems.append(f"money in accounts is {total} but start + deposits - withdrawals = {expected}")
    negative = scalar(conn, "SELECT COUNT(*) FROM accounts WHERE balance < 0")
    if negative:
        problems.append(f"{negative} account(s) with a negative balance")
    pending = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE status <> 'success'")
    if pending:
        problems.append(f"{pending} transaction(s) not in 'success' state")
    deposit_n = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type IN ('deposit','withdrawal')")
    transfer_n = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type='transfer'")
    audit_n = scalar(conn, "SELECT COUNT(*) FROM audit_log")
    if audit_n != deposit_n + 2 * transfer_n:
        problems.append(f"audit_log has {audit_n} rows, expected {deposit_n + 2 * transfer_n}")
    open_trx = scalar(conn, "SELECT COUNT(*) FROM information_schema.innodb_trx")
    return problems, open_trx


def server_log_errors(start_offset):
    """Lines the backend wrote to its log after `start_offset` that look like errors."""
    log = config.REPORTS_DIR / "backend_server.log"
    if not log.exists():
        return []
    data = log.read_text(encoding="utf-8", errors="replace")[start_offset:]
    return [l for l in data.splitlines() if "error" in l.lower() or "deadlock" in l.lower()]


def server_log_size():
    log = config.REPORTS_DIR / "backend_server.log"
    return len(log.read_text(encoding="utf-8", errors="replace")) if log.exists() else 0
