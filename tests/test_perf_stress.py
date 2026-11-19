"""Stress, spike and recovery testing (STR-xx), driven by Locust and by bursts of simultaneous requests.

    python -m pytest -m stress

Load testing asks "is it fast enough at normal traffic?". Stress testing pushes far past normal traffic
to see HOW the system fails and whether it recovers:
  * step stress: 20 -> 50 -> 100 -> 150 simultaneous users over 60 seconds        (STR-01..05)
  * spike: calm, then 100 users appear within a second, then calm again            (STR-06..09)
  * bursts: 100 simultaneous logins / transfers, 200 simultaneous reads, big bodies (STR-10..13)

What "passes" means: the server never crashes, never returns a 5xx error, never loses or invents money,
and goes back to normal speed afterwards. Slower responses under extreme load are expected and allowed.
"""
import time

import pytest

import perf_support as P
from api_client import parallel
from helpers import balance, connect, scalar

pytestmark = [pytest.mark.stress, pytest.mark.api]


@pytest.fixture(autouse=True)
def reset_data():
    """Override the global per-test reset: these tests inspect the data a stress run left behind."""
    yield


@pytest.fixture
def seeded():
    """Burst tests need the normal seed data (Alice 5000, Bob 3000), whatever ran before them."""
    c = connect()
    P.reseed(c)
    c.close()


@pytest.fixture
def conn():
    c = connect()
    yield c
    c.close()


def five_xx(result):
    return [f for f in result["failures"] if "500" in f["Error"] or "502" in f["Error"] or "503" in f["Error"]]


# ------------------------------------------------ 1. step stress
@pytest.fixture(scope="module")
def stress(api_server):
    c = connect()
    money = P.provision(c)
    c.close()
    log_start = P.server_log_size()
    result = P.run_locust("locust_stress.py", ["Customer", "ProbeUser"], tag="stress",
                          extra_env={"PERF_PROBE_FILE": str(P.OUT_DIR / "stress_probe.jsonl")})
    result.update(money_at_start=money, log_start=log_start)
    return result


def test_STR_01_server_survives_150_simultaneous_users_and_still_answers(stress, api):
    assert P.count(stress["total"]) > 2000, "the stress run did not generate enough traffic"
    assert api.get("/api/health").status_code == 200


def test_STR_02_no_5xx_errors_and_under_one_percent_failures_during_stress(stress):
    total = P.count(stress["total"])
    failed = P.count(stress["total"], "Failure Count")
    assert not five_xx(stress), five_xx(stress)[:3]
    assert failed / total <= 0.01, f"{failed} of {total} requests failed: {stress['failures'][:3]}"


def test_STR_03_slowdown_under_stress_is_bounded_no_request_waits_over_ten_seconds(stress):
    slowest = max(float(r["Max Response Time"]) for r in stress["stats"].values() if r["Name"] != "Aggregated")
    assert slowest < 10_000, f"slowest request took {slowest:.0f} ms"


def test_STR_04_books_balance_after_stress(stress, conn):
    problems, _ = P.ledger_problems(conn, stress["money_at_start"])
    assert not [p for p in problems if "audit_log" not in p and "not in 'success'" not in p], problems
    assert scalar(conn, "SELECT COUNT(*) FROM audit_log") == \
        scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type IN ('deposit','withdrawal')") + \
        2 * scalar(conn, "SELECT COUNT(*) FROM transactions WHERE type = 'transfer'")


def test_STR_05_backend_log_shows_no_deadlocks_or_unhandled_errors_during_stress(stress):
    errors = P.server_log_errors(stress["log_start"])
    assert errors == [], errors[:5]


# ------------------------------------------------ 2. spike and recovery
@pytest.fixture(scope="module")
def spike(api_server):
    c = connect()
    money = P.provision(c)
    c.close()
    probe = P.OUT_DIR / "spike_probe.jsonl"
    phases = P.OUT_DIR / "spike_phases.jsonl"
    P.OUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in (probe, phases):
        f.unlink(missing_ok=True)
    result = P.run_locust("locust_spike.py", ["Customer", "ProbeUser"], tag="spike",
                          extra_env={"PERF_PROBE_FILE": str(probe), "PERF_PHASE_FILE": str(phases)})
    phase_start = {p["phase"]: p["t"] for p in P.read_json_lines(phases)}
    samples = P.read_json_lines(probe)

    def between(a, b):
        lo, hi = phase_start[a], phase_start.get(b, float("inf"))
        return [s for s in samples if lo <= s["t"] < hi]

    result.update(
        money_at_start=money,
        baseline=between("baseline", "spike"),
        during=between("spike", "recovery"),
        # skip the first 5 s after the spike ends: queued requests are still draining
        after=[s for s in between("recovery", "end") if s["t"] >= phase_start["recovery"] + 5],
    )
    return result


def test_STR_06_no_5xx_errors_when_traffic_jumps_from_5_to_100_users(spike):
    assert not five_xx(spike), five_xx(spike)[:3]
    assert P.count(spike["total"], "Failure Count") / P.count(spike["total"]) <= 0.01, spike["failures"][:3]


def test_STR_07_every_probe_request_is_answered_during_the_spike(spike):
    assert len(spike["during"]) >= 5, "the probe user did not run during the spike"
    bad = [s for s in spike["during"] if s["status"] != 200]
    assert not bad, f"{len(bad)} of {len(spike['during'])} probe requests failed during the spike: {bad[:3]}"


def test_STR_08_response_time_returns_to_normal_within_five_seconds_after_the_spike(spike):
    base = P.percentile([s["ms"] for s in spike["baseline"]], 50)
    after = P.percentile([s["ms"] for s in spike["after"]], 50)
    assert len(spike["after"]) >= 10, "no probe samples after the spike"
    limit = max(3 * base, 250)
    assert after <= limit, f"median {after:.0f} ms after the spike vs {base:.0f} ms before (limit {limit:.0f} ms)"


def test_STR_09_data_is_consistent_and_no_transaction_is_left_open_after_the_spike(spike, conn):
    problems, open_trx = P.ledger_problems(conn, spike["money_at_start"])
    assert not [p for p in problems if "audit_log" not in p and "not in 'success'" not in p], problems
    time.sleep(1)
    assert scalar(conn, "SELECT COUNT(*) FROM information_schema.innodb_trx") == 0


# ------------------------------------------------ 3. bursts of simultaneous requests
def test_STR_10_one_hundred_simultaneous_logins_all_succeed_and_the_server_stays_responsive(seeded, api):
    results = parallel([lambda: api.post("/api/auth/login", json={"email": "alice@example.com", "password": "password123"})
                        for _ in range(100)])
    assert [r.status_code for r in results].count(200) == 100
    started = time.perf_counter()
    assert api.get("/api/health").status_code == 200
    assert time.perf_counter() - started < 1.0, "server was still choking after the login burst"


def test_STR_11_one_hundred_simultaneous_opposite_transfers_cause_no_deadlock_and_keep_the_total(seeded, api, alice, bob, db):
    total_before = balance(db, 1) + balance(db, 2)
    calls = [(lambda: api.transfer(alice, 1, 2, "1.00")) if i % 2 == 0 else (lambda: api.transfer(bob, 2, 1, "1.00"))
             for i in range(100)]
    results = parallel(calls)
    codes = [r.status_code for r in results]
    assert codes.count(201) == 100, f"unexpected responses: {[r.text for r in results if r.status_code != 201][:3]}"
    assert balance(db, 1) + balance(db, 2) == total_before
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000          # 50 each way cancels out


def test_STR_12_two_hundred_simultaneous_reads_queue_for_the_connection_pool_and_all_succeed(seeded, api, alice):
    results = parallel([lambda: api.get("/api/accounts", alice) for _ in range(200)])
    assert all(r.status_code == 200 for r in results), [r.status_code for r in results if r.status_code != 200][:5]


def test_STR_13_burst_of_large_request_bodies_does_not_crash_the_server(seeded, api, alice):
    big_ok = '{"account_id": 1, "amount": "1.00", "pad": "' + "x" * 90_000 + '"}'       # under the 100 kb limit
    too_big = '{"account_id": 1, "amount": "1.00", "pad": "' + "x" * 150_000 + '"}'      # over the limit
    headers = {"Content-Type": "application/json"}
    calls = [(lambda: api.post("/api/transactions/deposit", alice, data=(big_ok if i % 2 else too_big), headers=headers))
             for i in range(50)]
    results = parallel(calls)
    codes = {r.status_code for r in results}
    assert codes <= {201, 400, 413}, codes
    assert api.get("/api/health").status_code == 200
