"""Performance / load testing with Locust (PRF-xxx).

Merged from: test_perf_load.py.
"""
import config
import perf_support as P
import pytest
import time
from helpers import connect, rows, run, scalar


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
@pytest.mark.performance
@pytest.mark.api
def test_PRF_01_no_request_fails_during_the_load_run(load):
    total = load["total"]
    assert P.count(total) > 500, f"only {P.count(total)} requests were made; the load run did not really run"
    assert P.count(total, "Failure Count") == 0, f"failures: {load['failures'][:5]}"


@pytest.mark.performance
@pytest.mark.api
def test_PRF_02_backend_log_shows_no_errors_during_the_load_run(load):
    errors = P.server_log_errors(load["log_start"])
    assert errors == [], errors[:5]


@pytest.mark.performance
@pytest.mark.api
def test_PRF_03_read_endpoints_p95_response_time_is_within_budget(load):
    slow = {n: P.p95(load["stats"][n]) for n in READ_ENDPOINTS if P.p95(load["stats"][n]) > P.READ_P95_MS}
    assert not slow, f"p95 over {P.READ_P95_MS} ms: {slow}"


@pytest.mark.performance
@pytest.mark.api
def test_PRF_04_money_endpoints_p95_response_time_is_within_budget(load):
    slow = {n: P.p95(load["stats"][n]) for n in MONEY_ENDPOINTS if P.p95(load["stats"][n]) > P.MONEY_P95_MS}
    assert not slow, f"p95 over {P.MONEY_P95_MS} ms: {slow}"


@pytest.mark.performance
@pytest.mark.api
def test_PRF_05_login_p95_response_time_is_within_budget(load):
    assert P.p95(load["stats"]["POST /api/auth/login"]) <= P.LOGIN_P95_MS


@pytest.mark.performance
@pytest.mark.api
def test_PRF_06_throughput_meets_the_minimum(load):
    rps = float(load["total"]["Requests/s"])
    assert rps >= P.MIN_REQUESTS_PER_SECOND, f"{rps:.1f} requests/s"


@pytest.mark.performance
@pytest.mark.api
def test_PRF_07_books_balance_after_the_load_run(load, conn):
    problems, _ = P.ledger_problems(conn, load["money_at_start"])
    assert not [p for p in problems if "audit_log" not in p and "not in 'success'" not in p], problems


@pytest.mark.performance
@pytest.mark.api
def test_PRF_08_audit_log_has_one_row_per_balance_change(load, conn):
    deposit_withdrawals = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type IN ('deposit','withdrawal')")
    transfers = scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type = 'transfer'")
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log") == deposit_withdrawals + 2 * transfers


@pytest.mark.performance
@pytest.mark.api
def test_PRF_09_no_database_transaction_is_left_open_and_no_row_is_stuck(load, conn):
    time.sleep(1)
    assert scalar(conn, "SELECT COUNT(*) FROM information_schema.innodb_trx") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM transactions WHERE status = 'pending'") == 0


# ------------------------------------------------ 2. one very busy account
@pytest.mark.performance
@pytest.mark.api
def test_PRF_10_every_deposit_into_the_hot_account_succeeds(hot):
    total = hot["total"]
    assert P.count(total) > 100, "the hot-account run did not really run"
    assert P.count(total, "Failure Count") == 0, hot["failures"][:5]


@pytest.mark.performance
@pytest.mark.api
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
@pytest.mark.performance
@pytest.mark.api
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
    """50,000 transactions spread over 202 accounts (about 250 rows per account), like a real bank:
    an index only helps when it picks a small slice of a big table."""
    c = connect()
    P.provision(c, users=200)                       # accounts 1-2 from the seed + 200 more
    accounts = 202
    batch = []
    for i in range(50_000):
        a = i % accounts + 1
        b = (i * 7 + 1) % accounts + 1
        if i % 3 == 0:
            batch.append((a, b if b != a else a % accounts + 1, "1.00", "transfer", "success", "bulk"))
        elif i % 3 == 1:
            batch.append((None, a, "1.00", "deposit", "success", "bulk"))
        else:
            batch.append((a, None, "1.00", "withdrawal", "success", "bulk"))
    with c.cursor() as cur:
        for i in range(0, len(batch), 5000):
            cur.executemany("INSERT INTO transactions (from_account_id, to_account_id, amount, type, status, description) "
                            "VALUES (%s, %s, %s, %s, %s, %s)", batch[i:i + 5000])
    run(c, "ANALYZE TABLE transactions")
    yield c
    c.close()


def plan_text(plan):
    """EXPLAIN output as one string. MySQL 8.4+ prints a text tree, older MySQL and MariaDB print columns;
    either way the names of the indexes used appear somewhere in the values."""
    return " ".join(str(v) for row in plan for v in row.values() if v is not None)


def timed(conn, sql, params=None):
    started = time.perf_counter()
    result = rows(conn, sql, params)
    return result, (time.perf_counter() - started) * 1000


@pytest.mark.performance
@pytest.mark.api
def test_PRF_13_transaction_lookups_by_account_use_the_indexes_on_a_50000_row_table(big_tables):
    """Each side of an account statement (money out, money in) must be an index lookup, not a table scan."""
    for column, index in (("from_account_id", "idx_txn_from"), ("to_account_id", "idx_txn_to")):
        text = plan_text(rows(big_tables, f"EXPLAIN SELECT * FROM transactions WHERE {column} = 1"))
        assert index in text, f"{column}: full table scan instead of {index}: {text}"


@pytest.mark.performance
@pytest.mark.api
def test_PRF_14_transaction_history_endpoint_stays_fast_with_50000_rows(big_tables, api):
    token = api.login("alice@example.com")
    api.get("/api/transactions", token)                       # warm-up
    started = time.perf_counter()
    r = api.get("/api/transactions", token)
    elapsed = (time.perf_counter() - started) * 1000
    assert r.status_code == 200
    assert elapsed < 3000, f"GET /api/transactions took {elapsed:.0f} ms with 50,000 transactions in the table"


@pytest.mark.performance
@pytest.mark.api
def test_PRF_15_admin_transaction_list_is_capped_at_200_rows(big_tables, api):
    token = api.login("admin@example.com")
    started = time.perf_counter()
    r = api.get("/api/admin/transactions", token)
    elapsed = (time.perf_counter() - started) * 1000
    assert r.status_code == 200 and len(r.json()) == 200
    assert elapsed < 2000, f"{elapsed:.0f} ms"


@pytest.mark.performance
@pytest.mark.api
def test_PRF_16_account_lookup_by_owner_uses_the_user_index(big_tables):
    plan = rows(big_tables, "EXPLAIN SELECT * FROM accounts WHERE user_id = 1")
    text = plan_text(plan)
    assert "idx_accounts_user" in text or "fk_account_user" in text, f"no index used: {text}"
