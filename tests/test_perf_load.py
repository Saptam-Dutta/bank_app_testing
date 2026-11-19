"""Performance / load testing (PRF-xx), driven by Locust.

    python -m pytest -m performance

A plain `pytest` skips these (they take about two minutes). They answer four questions:
  1. Does the API stay correct and error-free with 25 customers using it at once?   (PRF-01..09)
  2. Does one very busy account stay correct under many simultaneous deposits?      (PRF-10, 11)
  3. How fast is a single user's request when nothing else is happening?            (PRF-12)
  4. Do the database indexes keep queries fast when the tables are large?           (PRF-13..16)

Locust's own CSV output is saved in tests/reports/perf/ so you can chart or quote the numbers.
"""
import time

import pytest

import config
import perf_support as P
from helpers import connect, rows, run, scalar

pytestmark = [pytest.mark.performance, pytest.mark.api]

LOAD_USERS_ONLINE = 25
LOAD_SECONDS = 30
HOT_USERS = 20
HOT_SECONDS = 15

READ_ENDPOINTS = ["GET /api/accounts", "GET /api/accounts/:id/statement", "GET /api/transactions",
                  "GET /api/branches", "GET /api/auth/me"]
MONEY_ENDPOINTS = ["POST /api/transactions/deposit", "POST /api/transactions/withdraw",
                   "POST /api/transactions/transfer"]


@pytest.fixture(autouse=True)
def reset_data():
    """Override the global per-test reset: these tests read the data a load run left behind."""
    yield


@pytest.fixture(scope="module")
def load(api_server):
    conn = connect()
    money_at_start = P.provision(conn)
    log_start = P.server_log_size()
    result = P.run_locust("locust_load.py", ["Customer"], users=LOAD_USERS_ONLINE, spawn_rate=5,
                          seconds=LOAD_SECONDS, tag="load")
    result.update(money_at_start=money_at_start, log_start=log_start)
    yield result
    conn.close()


@pytest.fixture(scope="module")
def hot(api_server):
    conn = connect()
    P.provision(conn)
    start_balance = scalar(conn, "SELECT balance FROM accounts WHERE account_id = 1")
    result = P.run_locust("locust_hot.py", ["HotAccount"], users=HOT_USERS, spawn_rate=HOT_USERS,
                          seconds=HOT_SECONDS, tag="hot")
    result["start_balance"] = start_balance
    yield result
    conn.close()


@pytest.fixture
def conn():
    c = connect()
    yield c
    c.close()


# ------------------------------------------------ 1. mixed load, 25 users, 30 seconds
def test_PRF_01_no_request_fails_during_the_load_run(load):
    total = load["total"]
    assert P.count(total) > 500, f"only {P.count(total)} requests were made; the load run did not really run"
    assert P.count(total, "Failure Count") == 0, f"failures: {load['failures'][:5]}"


def test_PRF_02_backend_log_shows_no_errors_during_the_load_run(load):
    errors = P.server_log_errors(load["log_start"])
    assert errors == [], errors[:5]


def test_PRF_03_read_endpoints_p95_response_time_is_within_budget(load):
    slow = {n: P.p95(load["stats"][n]) for n in READ_ENDPOINTS if P.p95(load["stats"][n]) > P.READ_P95_MS}
    assert not slow, f"p95 over {P.READ_P95_MS} ms: {slow}"


def test_PRF_04_money_endpoints_p95_response_time_is_within_budget(load):
    slow = {n: P.p95(load["stats"][n]) for n in MONEY_ENDPOINTS if P.p95(load["stats"][n]) > P.MONEY_P95_MS}
    assert not slow, f"p95 over {P.MONEY_P95_MS} ms: {slow}"


def test_PRF_05_login_p95_response_time_is_within_budget(load):
    assert P.p95(load["stats"]["POST /api/auth/login"]) <= P.LOGIN_P95_MS


def test_PRF_06_throughput_meets_the_minimum(load):
    rps = float(load["total"]["Requests/s"])
    assert rps >= P.MIN_REQUESTS_PER_SECOND, f"{rps:.1f} requests/s"


def test_PRF_07_books_balance_after_the_load_run(load, conn):
    problems, _ = P.ledger_problems(conn, load["money_at_start"])
    assert not [p for p in problems if "audit_log" not in p and "not in 'success'" not in p], problems


def test_PRF_08_audit_log_has_one_row_per_balance_change(load, conn):
    deposit_withdrawals = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type IN ('deposit','withdrawal')")
    transfers = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type = 'transfer'")
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log") == deposit_withdrawals + 2 * transfers


def test_PRF_09_no_database_transaction_is_left_open_and_no_row_is_stuck(load, conn):
    time.sleep(1)
    assert scalar(conn, "SELECT COUNT(*) FROM information_schema.innodb_trx") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM transactions WHERE status = 'pending'") == 0


# ------------------------------------------------ 2. one very busy account
def test_PRF_10_every_deposit_into_the_hot_account_succeeds(hot):
    total = hot["total"]
    assert P.count(total) > 100, "the hot-account run did not really run"
    assert P.count(total, "Failure Count") == 0, hot["failures"][:5]


def test_PRF_11_hot_account_balance_equals_start_plus_every_recorded_deposit(hot, conn):
    """No lost updates: the balance must equal the starting balance plus exactly the deposits the ledger
    holds, and every deposit Locust saw succeed must be in the ledger. (Locust's own counter can trail the
    server by a second or so at shutdown, so the ledger, not Locust, is the source of truth.)"""
    stats = hot["stats"]["POST deposit (hot account)"]
    reported_ok = P.count(stats) - P.count(stats, "Failure Count")
    ledger = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE to_account_id = 1 AND type = 'deposit' AND status = 'success'")
    assert scalar(conn, "SELECT balance FROM accounts WHERE account_id = 1") == hot["start_balance"] + ledger
    assert ledger >= reported_ok, f"{reported_ok} deposits were acknowledged to clients but only {ledger} are in the ledger"
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log WHERE account_id = 1") == ledger


# ------------------------------------------------ 3. single-user latency
def test_PRF_12_single_user_requests_are_fast_when_the_system_is_idle(api, alice):
    timings = []
    for _ in range(30):
        started = time.perf_counter()
        assert api.get("/api/accounts", alice).status_code == 200
        timings.append((time.perf_counter() - started) * 1000)
    median = P.percentile(timings, 50)
    assert median < 250, f"median {median:.0f} ms for GET /api/accounts with no load"


# ------------------------------------------------ 4. database speed with big tables
@pytest.fixture(scope="module")
def big_tables(api_server):
    """50,000 transactions spread across the two seed accounts (plus the matching audit rows are not needed)."""
    c = connect()
    P.provision(c, users=2)
    batch = [(1, 2, "1.00", "transfer", "success", "bulk") if i % 3 == 0 else
             (None, 1, "1.00", "deposit", "success", "bulk") if i % 3 == 1 else
             (2, None, "1.00", "withdrawal", "success", "bulk") for i in range(50_000)]
    with c.cursor() as cur:
        for i in range(0, len(batch), 5000):
            cur.executemany("INSERT INTO transactions (from_account_id, to_account_id, amount, type, status, description) "
                            "VALUES (%s, %s, %s, %s, %s, %s)", batch[i:i + 5000])
    run(c, "ANALYZE TABLE transactions")
    yield c
    c.close()


def timed(conn, sql, params=None):
    started = time.perf_counter()
    result = rows(conn, sql, params)
    return result, (time.perf_counter() - started) * 1000


def test_PRF_13_account_statement_query_uses_an_index_on_a_50000_row_table(big_tables):
    plan = rows(big_tables, "EXPLAIN SELECT * FROM transactions WHERE from_account_id = 1 OR to_account_id = 1 "
                            "ORDER BY created_at DESC")
    keys = " ".join(str(r.get("key") or "") + str(r.get("possible_keys") or "") for r in plan)
    assert "idx_txn_from" in keys or "idx_txn_to" in keys, plan


def test_PRF_14_transaction_history_endpoint_stays_fast_with_50000_rows(big_tables, api):
    token = api.login("alice@example.com")
    api.get("/api/transactions", token)                       # warm-up
    started = time.perf_counter()
    r = api.get("/api/transactions", token)
    elapsed = (time.perf_counter() - started) * 1000
    assert r.status_code == 200
    assert elapsed < 3000, f"GET /api/transactions took {elapsed:.0f} ms with 50,000 transactions in the table"


def test_PRF_15_admin_transaction_list_is_capped_at_200_rows(big_tables, api):
    token = api.login("admin@example.com")
    started = time.perf_counter()
    r = api.get("/api/admin/transactions", token)
    elapsed = (time.perf_counter() - started) * 1000
    assert r.status_code == 200 and len(r.json()) == 200
    assert elapsed < 2000, f"{elapsed:.0f} ms"


def test_PRF_16_account_lookup_by_owner_uses_the_user_index(big_tables):
    plan = rows(big_tables, "EXPLAIN SELECT * FROM accounts WHERE user_id = 1")
    assert any("idx_accounts_user" in str(r.get("key") or "") or "fk_account_user" in str(r.get("key") or "")
               for r in plan), plan
