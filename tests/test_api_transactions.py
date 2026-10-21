"""API testing: deposits, withdrawals, transfers, history and concurrency (API-TXN-xx)."""
from decimal import Decimal

import pytest

from api_client import parallel
from helpers import audit_count, balance, rows, run, scalar, total_balance

pytestmark = pytest.mark.api


def D(value):
    return Decimal(str(value))


def txn_count(db):
    return scalar(db, "SELECT COUNT(*) FROM transactions")


# ------------------------------------------------------------------ deposit
def test_API_TXN_01_deposit_increases_balance_and_records_transaction(api, alice, db):
    r = api.deposit(alice, 1, 250.50)
    assert r.status_code == 201 and r.json()["transaction_id"]
    assert balance(db, 1) == D("5250.50")
    t = rows(db, "SELECT * FROM transactions")[0]
    assert (t["type"], t["status"], t["from_account_id"], t["to_account_id"]) == ("deposit", "success", None, 1)
    assert t["amount"] == D("250.50")


def test_API_TXN_02_deposit_writes_an_audit_log_entry(api, alice, db):
    api.deposit(alice, 1, 100)
    assert audit_count(db, 1) == 1


def test_API_TXN_03_deposit_accepts_amount_as_a_string(api, alice, db):
    assert api.deposit(alice, 1, "10.25").status_code == 201
    assert balance(db, 1) == D("5010.25")


def test_API_TXN_04_smallest_valid_deposit_is_one_paisa(api, alice, db):
    """Boundary value."""
    assert api.deposit(alice, 1, 0.01).status_code == 201
    assert balance(db, 1) == D("5000.01")


BAD_AMOUNTS = [0, -5, "abc", "", None, 0.001, "10.999", "1e3", "0x10", [5], {"a": 1}, True, " ", "--5"]


@pytest.mark.parametrize("amount", BAD_AMOUNTS)
def test_API_TXN_05_deposit_with_invalid_amount_returns_400_and_changes_nothing(api, alice, db, amount):
    assert api.deposit(alice, 1, amount).status_code == 400
    assert balance(db, 1) == 5000 and txn_count(db) == 0


def test_API_TXN_06_deposit_without_amount_returns_400(api, alice):
    assert api.post("/api/transactions/deposit", alice, {"account_id": 1}).status_code == 400


BAD_IDS = ["abc", 0, -1, 1.5, None, {"$gt": 0}, [1], "1 OR 1=1", "1; DROP TABLE accounts"]


@pytest.mark.parametrize("account_id", BAD_IDS)
def test_API_TXN_07_deposit_with_invalid_account_id_returns_400(api, alice, account_id):
    assert api.deposit(alice, account_id, 10).status_code == 400


def test_API_TXN_08_cannot_deposit_into_someone_elses_account(api, alice, db):
    assert api.deposit(alice, 2, 100).status_code == 404
    assert balance(db, 2) == 3000


def test_API_TXN_09_deposit_into_nonexistent_account_returns_404(api, alice):
    assert api.deposit(alice, 99999, 10).status_code == 404


@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_10_deposit_into_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 1", (status,))
    assert api.deposit(alice, 1, 10).status_code == 400
    assert balance(db, 1) == 5000


def test_API_TXN_11_deposit_requires_login(api):
    assert api.deposit(None, 1, 10).status_code == 401


def test_API_TXN_12_deposit_that_would_overflow_the_balance_column_returns_4xx(api, alice, db):
    """DECIMAL(15,2) holds at most 9,999,999,999,999.99. Overflowing it must be a clean
    client error, not a 500."""
    r = api.deposit(alice, 1, "9999999999999.99")
    assert 400 <= r.status_code < 500, f"got {r.status_code}: {r.text}"
    assert balance(db, 1) == 5000


# --------------------------------------------------------------- withdrawal
def test_API_TXN_13_withdraw_decreases_balance_and_records_transaction(api, alice, db):
    r = api.withdraw(alice, 1, 1200.75)
    assert r.status_code == 201
    assert balance(db, 1) == D("3799.25")
    t = rows(db, "SELECT * FROM transactions")[0]
    assert (t["type"], t["status"], t["from_account_id"], t["to_account_id"]) == ("withdrawal", "success", 1, None)


def test_API_TXN_14_withdraw_entire_balance_leaves_zero(api, alice, db):
    """Boundary value: balance == amount is allowed."""
    assert api.withdraw(alice, 1, 5000).status_code == 201
    assert balance(db, 1) == 0


def test_API_TXN_15_withdraw_one_paisa_more_than_balance_is_refused(api, alice, db):
    """Boundary value."""
    assert api.withdraw(alice, 1, "5000.01").status_code == 400
    assert balance(db, 1) == 5000 and txn_count(db) == 0


def test_API_TXN_16_withdraw_from_empty_account_is_refused(api, alice, db):
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    assert api.withdraw(alice, 1, 1).status_code == 400


@pytest.mark.parametrize("amount", BAD_AMOUNTS)
def test_API_TXN_17_withdraw_with_invalid_amount_returns_400(api, alice, db, amount):
    assert api.withdraw(alice, 1, amount).status_code == 400
    assert balance(db, 1) == 5000


@pytest.mark.parametrize("account_id", BAD_IDS)
def test_API_TXN_18_withdraw_with_invalid_account_id_returns_400(api, alice, account_id):
    assert api.withdraw(alice, account_id, 10).status_code == 400


def test_API_TXN_19_cannot_withdraw_from_someone_elses_account(api, alice, db):
    assert api.withdraw(alice, 2, 100).status_code == 404
    assert balance(db, 2) == 3000


@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_20_withdraw_from_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 1", (status,))
    assert api.withdraw(alice, 1, 10).status_code == 400
    assert balance(db, 1) == 5000


def test_API_TXN_21_withdraw_requires_login(api):
    assert api.withdraw(None, 1, 10).status_code == 401


# ----------------------------------------------------------------- transfer
def test_API_TXN_22_transfer_moves_money_between_accounts(api, alice, db):
    r = api.transfer(alice, 1, 2, 500, description="Rent")
    assert r.status_code == 201
    assert balance(db, 1) == 4500 and balance(db, 2) == 3500
    t = rows(db, "SELECT * FROM transactions")[0]
    assert (t["type"], t["status"], t["from_account_id"], t["to_account_id"], t["description"]) == \
           ("transfer", "success", 1, 2, "Rent")


def test_API_TXN_23_transfer_uses_default_description(api, alice, db):
    api.transfer(alice, 1, 2, 10)
    assert scalar(db, "SELECT description FROM transactions") == "Fund transfer"


def test_API_TXN_24_transfer_keeps_total_money_constant(api, alice, db):
    before = total_balance(db)
    api.transfer(alice, 1, 2, "123.45")
    assert total_balance(db) == before


def test_API_TXN_25_transfer_creates_audit_entries_for_both_accounts(api, alice, db):
    api.transfer(alice, 1, 2, 100)
    assert audit_count(db, 1) == 1 and audit_count(db, 2) == 1


def test_API_TXN_26_transfer_between_own_accounts(api, alice, db):
    new_id = api.post("/api/accounts", alice, {"branch_id": 1, "account_type": "current"}).json()["account_id"]
    assert api.transfer(alice, 1, new_id, 1000).status_code == 201
    assert balance(db, new_id) == 1000 and balance(db, 1) == 4000


def test_API_TXN_27_transfer_to_the_same_account_is_refused(api, alice, db):
    assert api.transfer(alice, 1, 1, 10).status_code == 400
    assert txn_count(db) == 0


@pytest.mark.parametrize("src,dst", [("1", 1), (1, "1"), ("1", "1")])
def test_API_TXN_28_same_account_check_works_across_string_and_number_ids(api, alice, db, src, dst):
    """Previously '1' !== 1 slipped past a strict-equality check."""
    assert api.transfer(alice, src, dst, 10).status_code == 400
    assert txn_count(db) == 0 and balance(db, 1) == 5000


def test_API_TXN_29_insufficient_funds_changes_nothing(api, alice, db):
    assert api.transfer(alice, 1, 2, 5000.01).status_code == 400
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000
    assert txn_count(db) == 0 and audit_count(db) == 0


def test_API_TXN_30_transfer_of_entire_balance_is_allowed(api, alice, db):
    assert api.transfer(alice, 1, 2, 5000).status_code == 201
    assert balance(db, 1) == 0 and balance(db, 2) == 8000


def test_API_TXN_31_cannot_transfer_from_someone_elses_account(api, alice, db):
    assert api.transfer(alice, 2, 1, 100).status_code == 404
    assert balance(db, 2) == 3000 and balance(db, 1) == 5000


def test_API_TXN_32_transfer_to_nonexistent_account_returns_404(api, alice, db):
    assert api.transfer(alice, 1, 99999, 10).status_code == 404
    assert balance(db, 1) == 5000


def test_API_TXN_33_transfer_from_nonexistent_account_returns_404(api, alice):
    assert api.transfer(alice, 99999, 1, 10).status_code == 404


@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_34_transfer_from_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 1", (status,))
    assert api.transfer(alice, 1, 2, 10).status_code == 400


@pytest.mark.parametrize("status", ["frozen", "closed"])
def test_API_TXN_35_transfer_to_inactive_account_returns_400(api, alice, db, status):
    run(db, "UPDATE accounts SET status = %s WHERE account_id = 2", (status,))
    assert api.transfer(alice, 1, 2, 10).status_code == 400
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000


@pytest.mark.parametrize("amount", BAD_AMOUNTS)
def test_API_TXN_36_transfer_with_invalid_amount_returns_400(api, alice, db, amount):
    assert api.transfer(alice, 1, 2, amount).status_code == 400
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000


@pytest.mark.parametrize("src,dst", [(None, 2), (1, None), ("abc", 2), (1, "abc"), (0, 2), (1, -2), ({"a": 1}, 2)])
def test_API_TXN_37_transfer_with_invalid_account_ids_returns_400(api, alice, src, dst):
    assert api.transfer(alice, src, dst, 10).status_code == 400


def test_API_TXN_38_transfer_description_of_255_chars_is_accepted(api, alice):
    """Boundary value."""
    assert api.transfer(alice, 1, 2, 1, description="d" * 255).status_code == 201


@pytest.mark.parametrize("description", ["d" * 256, 123, {"a": 1}, ["x"]])
def test_API_TXN_39_invalid_description_returns_400(api, alice, db, description):
    assert api.transfer(alice, 1, 2, 1, description=description).status_code == 400
    assert balance(db, 1) == 5000


def test_API_TXN_40_transfer_requires_login(api):
    assert api.transfer(None, 1, 2, 10).status_code == 401


def test_API_TXN_41_sql_injection_in_description_is_stored_as_plain_text(api, alice, db):
    payload = "x'); DROP TABLE accounts; --"
    assert api.transfer(alice, 1, 2, 1, description=payload).status_code == 201
    assert scalar(db, "SELECT description FROM transactions") == payload
    assert scalar(db, "SELECT COUNT(*) FROM accounts") == 2


# ------------------------------------------------------------------ history
def test_API_TXN_42_history_shows_only_my_transactions(api, alice, bob):
    api.deposit(alice, 1, 10)
    api.deposit(bob, 2, 20)
    mine = api.get("/api/transactions", alice).json()
    assert len(mine) == 1 and mine[0]["to_account_id"] == 1


def test_API_TXN_43_history_includes_incoming_and_outgoing_transfers(api, alice, bob):
    api.transfer(alice, 1, 2, 100)
    api.transfer(bob, 2, 1, 50)
    assert len(api.get("/api/transactions", alice).json()) == 2
    assert len(api.get("/api/transactions", bob).json()) == 2


def test_API_TXN_44_history_is_newest_first(api, alice):
    for amount in (1, 2, 3):
        api.deposit(alice, 1, amount)
    amounts = [D(t["amount"]) for t in api.get("/api/transactions", alice).json()]
    assert amounts == [3, 2, 1]


def test_API_TXN_45_history_is_empty_for_a_user_with_no_activity(api, alice):
    assert api.get("/api/transactions", alice).json() == []


def test_API_TXN_46_history_requires_login(api):
    assert api.get("/api/transactions").status_code == 401


def test_API_TXN_47_failed_attempts_do_not_appear_in_history(api, alice):
    api.withdraw(alice, 1, 999999)
    assert api.get("/api/transactions", alice).json() == []


# -------------------------------------------------------------- concurrency
def test_API_TXN_48_simultaneous_withdrawals_cannot_overdraw(api, alice, db):
    """10 withdrawals of 1000 fired at once against a 5000 balance: exactly 5 succeed."""
    codes = parallel([lambda: api.withdraw(alice, 1, 1000).status_code for _ in range(10)])
    assert codes.count(201) == 5 and codes.count(400) == 5, codes
    assert balance(db, 1) == 0
    assert txn_count(db) == 5 and audit_count(db, 1) == 5


def test_API_TXN_49_simultaneous_transfers_cannot_overdraw(api, alice, db):
    """4 transfers of 3000 from a 5000 account at once: exactly one can succeed."""
    codes = parallel([lambda: api.transfer(alice, 1, 2, 3000).status_code for _ in range(4)])
    assert codes.count(201) == 1 and codes.count(400) == 3, codes
    assert balance(db, 1) == 2000 and balance(db, 2) == 6000


def test_API_TXN_50_simultaneous_deposits_lose_no_updates(api, alice, db):
    codes = parallel([lambda: api.deposit(alice, 1, 10).status_code for _ in range(15)])
    assert codes == [201] * 15
    assert balance(db, 1) == 5150 and txn_count(db) == 15


def test_API_TXN_51_opposite_direction_transfers_do_not_deadlock(api, alice, bob, db):
    """A->B and B->A at the same moment, 8 each. Locks are taken lowest-id-first, so no
    request may fail with 500 and the money must balance exactly."""
    before = total_balance(db)
    calls = [(lambda: api.transfer(alice, 1, 2, 10).status_code) if i % 2 == 0
             else (lambda: api.transfer(bob, 2, 1, 10).status_code) for i in range(16)]
    codes = parallel(calls)
    assert codes == [201] * 16, codes
    assert total_balance(db) == before
    assert balance(db, 1) == 5000 and balance(db, 2) == 3000


def test_API_TXN_52_mixed_simultaneous_operations_keep_totals_consistent(api, alice, bob, db):
    """Deposits, withdrawals and transfers all at once; the ledger must reconcile."""
    calls = ([lambda: api.deposit(alice, 1, 100).status_code] * 5 +
             [lambda: api.withdraw(bob, 2, 100).status_code] * 5 +
             [lambda: api.transfer(alice, 1, 2, 50).status_code] * 5)
    codes = parallel(calls)
    assert 500 not in codes and all(c == 201 for c in codes), codes
    assert balance(db, 1) == 5000 + 500 - 250
    assert balance(db, 2) == 3000 - 500 + 250


@pytest.mark.xfail(reason="KNOWN GAP (reported, not fixed): refused or failed money movements are not "
                          "recorded; the 'failed' status exists in the schema but is never written.",
                   strict=False)
def test_API_TXN_53_refused_transfer_is_recorded_with_status_failed(api, alice, db):
    api.transfer(alice, 1, 2, 999999)
    assert scalar(db, "SELECT COUNT(*) FROM transactions WHERE status = 'failed'") == 1


def test_API_TXN_54_transfer_that_would_overflow_the_receivers_balance_returns_4xx(api, alice, db):
    """Same limit as TXN_12, on the receiving side of a transfer."""
    run(db, "UPDATE accounts SET balance = 9999999999999.00 WHERE account_id = 2")
    r = api.transfer(alice, 1, 2, 5000)
    assert 400 <= r.status_code < 500, f"got {r.status_code}: {r.text}"
    assert balance(db, 1) == 5000 and balance(db, 2) == D("9999999999999.00")
    assert txn_count(db) == 0


def test_API_TXN_55_deposit_up_to_exactly_the_maximum_balance_is_allowed(api, alice, db):
    """Boundary value: 5000 + 9,999,999,994,999.99 = 9,999,999,999,999.99, the column maximum."""
    assert api.deposit(alice, 1, "9999999994999.99").status_code == 201
    assert balance(db, 1) == D("9999999999999.99")
    assert api.deposit(alice, 1, "0.01").status_code == 400
