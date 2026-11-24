"""Database testing: constraints, referential integrity, trigger, transactions, locking, schema (DB-xxx).

Merged from: test_db_constraints.py, test_db_integrity.py, test_db_triggers.py, test_db_transactions.py, test_db_locking.py, test_db_schema.py.
"""
import pymysql
import pytest
import threading
import time
from config import TEST_DB_NAME
from decimal import Decimal
from helpers import audit_count, balance, connect, ER_BAD_NULL, ER_CHECK_VIOLATED, ER_DATA_TRUNCATED, ER_DUP_ENTRY, ER_LOCK_DEADLOCK, ER_LOCK_WAIT_TIMEOUT, ER_NO_REFERENCED_ROW, ER_ROW_IS_REFERENCED, make_account, make_user, mysql_errno, one, rows, run, scalar, total_balance


# ============================================================================
# db constraints
# ============================================================================

@pytest.mark.database
def test_DB_CON_01_balance_cannot_be_updated_below_zero(db):
    """CHECK (balance >= 0): overdrawing an account directly in SQL is rejected."""
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET balance = -0.01 WHERE account_id = 1")
    assert mysql_errno(e) == ER_CHECK_VIOLATED
    assert balance(db, 1) == 5000


@pytest.mark.database
def test_DB_CON_02_withdrawing_more_than_balance_is_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET balance = balance - 5000.01 WHERE account_id = 1")
    assert mysql_errno(e) == ER_CHECK_VIOLATED
    assert balance(db, 1) == 5000


@pytest.mark.database
def test_DB_CON_03_account_cannot_be_inserted_with_negative_balance(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_account(db, 1, balance=-10)
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_04_balance_of_exactly_zero_is_allowed(db):
    """Boundary value: 0.00 is valid."""
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    assert balance(db, 1) == 0


@pytest.mark.database
def test_DB_CON_05_transaction_amount_zero_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (NULL, 1, 0, 'deposit')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_06_transaction_amount_negative_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (NULL, 1, -50, 'deposit')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_07_smallest_valid_amount_is_accepted(db):
    """Boundary value: 0.01 is valid."""
    run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
            "VALUES (NULL, 1, 0.01, 'deposit')")
    assert one(db, "SELECT COUNT(*) AS c FROM transactions")["c"] == 1


@pytest.mark.database
def test_DB_CON_08_duplicate_email_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_user(db, "alice@example.com")
    assert mysql_errno(e) == ER_DUP_ENTRY


@pytest.mark.database
def test_DB_CON_09_duplicate_ifsc_code_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO branches (branch_name, ifsc_code) VALUES ('Clone', 'BANK0001234')")
    assert mysql_errno(e) == ER_DUP_ENTRY


@pytest.mark.database
def test_DB_CON_10_user_name_cannot_be_null(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO users (name, email, password_hash) VALUES (NULL, 'n@x.com', 'h')")
    assert mysql_errno(e) == ER_BAD_NULL


@pytest.mark.database
def test_DB_CON_11_password_hash_cannot_be_null(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO users (name, email, password_hash) VALUES ('N', 'n@x.com', NULL)")
    assert mysql_errno(e) == ER_BAD_NULL


@pytest.mark.database
def test_DB_CON_12_invalid_role_value_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO users (name, email, password_hash, role) "
                "VALUES ('N', 'n@x.com', 'h', 'superuser')")
    assert mysql_errno(e) == ER_DATA_TRUNCATED


@pytest.mark.database
def test_DB_CON_13_invalid_account_status_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET status = 'suspended' WHERE account_id = 1")
    assert mysql_errno(e) == ER_DATA_TRUNCATED


@pytest.mark.database
def test_DB_CON_14_invalid_transaction_type_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 2, 10, 'refund')")
    assert mysql_errno(e) == ER_DATA_TRUNCATED


@pytest.mark.database
def test_DB_CON_15_loan_amount_must_be_positive(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (1, -1000, 8.5, 12)")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_16_loan_tenure_must_be_positive(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (1, 1000, 8.5, 0)")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_17_loan_interest_rate_cannot_be_negative(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (1, 1000, -1, 12)")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_18_valid_loan_is_accepted(db):
    """Positive control: a sensible loan row is stored with status 'pending'."""
    run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
            "VALUES (1, 100000, 8.5, 24)")
    assert one(db, "SELECT status FROM loans")["status"] == "pending"


@pytest.mark.database
def test_DB_CON_19_deposit_must_not_have_a_source_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 2, 10, 'deposit')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_20_withdrawal_must_not_have_a_destination_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 2, 10, 'withdrawal')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_21_transfer_to_same_account_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 1, 10, 'transfer')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_22_transfer_requires_both_accounts(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, NULL, 10, 'transfer')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


@pytest.mark.database
def test_DB_CON_23_valid_transfer_row_is_accepted(db):
    """Positive control for the shape constraint."""
    run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
            "VALUES (1, 2, 10, 'transfer')")
    assert one(db, "SELECT COUNT(*) AS c FROM transactions")["c"] == 1

# ============================================================================
# db integrity
# ============================================================================

@pytest.mark.database
def test_DB_REF_01_account_needs_an_existing_user(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_account(db, user_id=9999)
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


@pytest.mark.database
def test_DB_REF_02_account_needs_an_existing_branch(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_account(db, user_id=1, branch_id=9999)
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


@pytest.mark.database
def test_DB_REF_03_transaction_source_account_must_exist(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (9999, NULL, 10, 'withdrawal')")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


@pytest.mark.database
def test_DB_REF_04_transaction_destination_account_must_exist(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (NULL, 9999, 10, 'deposit')")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


@pytest.mark.database
def test_DB_REF_05_loan_needs_an_existing_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (9999, 1000, 8, 12)")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


@pytest.mark.database
def test_DB_REF_06_deleting_a_user_cascades_to_their_accounts(db):
    uid = make_user(db, "temp@example.com")
    acc = make_account(db, uid)
    run(db, "DELETE FROM users WHERE user_id = %s", (uid,))
    assert scalar(db, "SELECT COUNT(*) FROM accounts WHERE account_id = %s", (acc,)) == 0


@pytest.mark.database
def test_DB_REF_07_deleting_an_account_cascades_to_its_loans(db):
    uid = make_user(db, "temp@example.com")
    acc = make_account(db, uid)
    run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
            "VALUES (%s, 1000, 8, 12)", (acc,))
    run(db, "DELETE FROM accounts WHERE account_id = %s", (acc,))
    assert scalar(db, "SELECT COUNT(*) FROM loans WHERE account_id = %s", (acc,)) == 0


@pytest.mark.database
def test_DB_REF_08_user_with_transaction_history_cannot_be_deleted(db):
    """Money history must not vanish: transactions reference accounts without CASCADE."""
    run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
            "VALUES (1, 2, 10, 'transfer')")
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "DELETE FROM users WHERE user_id = 1")
    assert mysql_errno(e) == ER_ROW_IS_REFERENCED
    assert scalar(db, "SELECT COUNT(*) FROM accounts WHERE user_id = 1") == 1


@pytest.mark.database
def test_DB_REF_09_branch_with_accounts_cannot_be_deleted(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "DELETE FROM branches WHERE branch_id = 1")
    assert mysql_errno(e) == ER_ROW_IS_REFERENCED


@pytest.mark.database
def test_DB_REF_10_account_with_audit_history_cannot_be_deleted(db):
    """Hardening fix: audit_log used to ON DELETE CASCADE, so deleting an account
    silently erased its audit trail. It must now be blocked."""
    run(db, "UPDATE accounts SET balance = balance + 1 WHERE account_id = 1")
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "DELETE FROM accounts WHERE account_id = 1")
    assert mysql_errno(e) == ER_ROW_IS_REFERENCED
    assert scalar(db, "SELECT COUNT(*) FROM audit_log WHERE account_id = 1") == 1


@pytest.mark.database
def test_DB_REF_11_audit_row_needs_an_existing_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO audit_log (account_id, action, old_balance, new_balance) "
                "VALUES (9999, 'X', 0, 1)")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW

# ============================================================================
# db triggers
# ============================================================================

@pytest.mark.database
def test_DB_TRG_01_balance_change_writes_one_audit_row(db):
    run(db, "UPDATE accounts SET balance = 5500 WHERE account_id = 1")
    log = rows(db, "SELECT * FROM audit_log WHERE account_id = 1")
    assert len(log) == 1
    assert log[0]["action"] == "BALANCE_UPDATE"


@pytest.mark.database
def test_DB_TRG_02_audit_row_stores_correct_old_and_new_balance(db):
    run(db, "UPDATE accounts SET balance = balance - 1250.75 WHERE account_id = 1")
    log = one(db, "SELECT * FROM audit_log WHERE account_id = 1")
    assert log["old_balance"] == Decimal("5000.00")
    assert log["new_balance"] == Decimal("3749.25")


@pytest.mark.database
def test_DB_TRG_03_audit_row_has_a_timestamp(db):
    run(db, "UPDATE accounts SET balance = 1 WHERE account_id = 1")
    assert one(db, "SELECT changed_at FROM audit_log")["changed_at"] is not None


@pytest.mark.database
def test_DB_TRG_04_status_change_alone_writes_no_audit_row(db):
    run(db, "UPDATE accounts SET status = 'frozen' WHERE account_id = 1")
    assert audit_count(db) == 0


@pytest.mark.database
def test_DB_TRG_05_update_to_same_balance_writes_no_audit_row(db):
    run(db, "UPDATE accounts SET balance = 5000 WHERE account_id = 1")
    assert audit_count(db) == 0


@pytest.mark.database
def test_DB_TRG_06_inserting_an_account_writes_no_audit_row(db):
    """The trigger is AFTER UPDATE only, so opening a new account is not logged."""
    make_account(db, 1, balance=100)
    assert audit_count(db) == 0


@pytest.mark.database
def test_DB_TRG_07_multi_row_update_writes_one_audit_row_per_account(db):
    run(db, "UPDATE accounts SET balance = balance + 10")
    assert audit_count(db, 1) == 1
    assert audit_count(db, 2) == 1
    assert audit_count(db) == 2


@pytest.mark.database
def test_DB_TRG_08_each_change_gets_its_own_audit_row_in_order(db):
    for amount in (100, 200, 300):
        run(db, "UPDATE accounts SET balance = %s WHERE account_id = 1", (amount,))
    log = rows(db, "SELECT old_balance, new_balance FROM audit_log WHERE account_id = 1 ORDER BY log_id")
    assert [(r["old_balance"], r["new_balance"]) for r in log] == [
        (Decimal("5000.00"), Decimal("100.00")),
        (Decimal("100.00"), Decimal("200.00")),
        (Decimal("200.00"), Decimal("300.00")),
    ]


@pytest.mark.database
def test_DB_TRG_09_rejected_update_leaves_no_audit_row(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET balance = -1 WHERE account_id = 1")
    assert mysql_errno(e) == ER_CHECK_VIOLATED
    assert audit_count(db) == 0


@pytest.mark.database
def test_DB_TRG_10_rolled_back_change_leaves_no_audit_row(db):
    """The audit insert is part of the same transaction as the balance change."""
    conn = connect(autocommit=False)
    try:
        run(conn, "UPDATE accounts SET balance = 1 WHERE account_id = 1")
        assert audit_count(conn) == 1          # visible inside the open transaction
        conn.rollback()
    finally:
        conn.close()
    assert audit_count(db) == 0


@pytest.mark.database
def test_DB_TRG_11_committed_change_keeps_its_audit_row(db):
    conn = connect(autocommit=False)
    try:
        run(conn, "UPDATE accounts SET balance = 1 WHERE account_id = 1")
        conn.commit()
    finally:
        conn.close()
    assert audit_count(db, 1) == 1


@pytest.mark.database
def test_DB_TRG_12_audit_entries_exist_for_both_sides_of_a_transfer(db):
    """What the API does for a transfer: debit one account, credit the other."""
    run(db, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(db, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    assert audit_count(db, 1) == 1 and audit_count(db, 2) == 1

# ============================================================================
# db transactions
# ============================================================================

@pytest.fixture
def conn():
    c = connect(autocommit=False)
    yield c
    c.rollback()
    c.close()


@pytest.mark.database
def test_DB_TXN_01_committed_transfer_persists(db, conn):
    run(conn, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    conn.commit()
    assert balance(db, 1) == Decimal("4500.00")
    assert balance(db, 2) == Decimal("3500.00")


@pytest.mark.database
def test_DB_TXN_02_rolled_back_transfer_changes_nothing(db, conn):
    run(conn, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    conn.rollback()
    assert balance(db, 1) == Decimal("5000.00")
    assert balance(db, 2) == Decimal("3000.00")


@pytest.mark.database
def test_DB_TXN_03_uncommitted_changes_are_invisible_to_other_sessions(db, conn):
    run(conn, "UPDATE accounts SET balance = 1 WHERE account_id = 1")
    assert balance(db, 1) == Decimal("5000.00")      # isolation: no dirty read
    conn.rollback()


@pytest.mark.database
def test_DB_TXN_04_failed_debit_midway_leaves_no_partial_update(db, conn):
    """Credit succeeds, then the debit violates CHECK(balance>=0). After rollback the
    credit must be gone too, and total money must be unchanged."""
    before = total_balance(db)
    run(conn, "UPDATE accounts SET balance = balance + 9000 WHERE account_id = 2")
    with pytest.raises(pymysql.MySQLError) as e:
        run(conn, "UPDATE accounts SET balance = balance - 9000 WHERE account_id = 1")
    assert mysql_errno(e) == ER_CHECK_VIOLATED
    conn.rollback()
    assert balance(db, 2) == Decimal("3000.00")
    assert total_balance(db) == before


@pytest.mark.database
def test_DB_TXN_05_rollback_also_removes_the_transaction_record(db, conn):
    run(conn, "INSERT INTO transactions (from_account_id, to_account_id, amount, type, status) "
              "VALUES (1, 2, 500, 'transfer', 'success')")
    conn.rollback()
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 0


@pytest.mark.database
def test_DB_TXN_06_rollback_removes_audit_rows_as_well(db, conn):
    run(conn, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    conn.rollback()
    assert audit_count(db) == 0


@pytest.mark.database
def test_DB_TXN_07_total_money_is_conserved_across_a_committed_transfer(db, conn):
    before = total_balance(db)
    run(conn, "UPDATE accounts SET balance = balance - 1234.56 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 1234.56 WHERE account_id = 2")
    conn.commit()
    assert total_balance(db) == before


@pytest.mark.database
def test_DB_TXN_08_a_failed_statement_does_not_commit_earlier_work_automatically(db, conn):
    """A statement error inside a transaction must not silently commit what came before."""
    run(conn, "UPDATE accounts SET balance = balance + 100 WHERE account_id = 2")
    with pytest.raises(pymysql.MySQLError):
        run(conn, "UPDATE accounts SET balance = -5 WHERE account_id = 1")
    conn.rollback()
    assert balance(db, 2) == Decimal("3000.00")

# ============================================================================
# db locking
# ============================================================================

@pytest.mark.database
def test_DB_LCK_01_locked_row_blocks_a_second_writer(db):
    holder = connect(autocommit=False)
    other = connect()
    try:
        run(holder, "SELECT * FROM accounts WHERE account_id = 1 FOR UPDATE")
        run(other, "SET SESSION innodb_lock_wait_timeout = 1")
        with pytest.raises(pymysql.MySQLError) as e:
            run(other, "UPDATE accounts SET balance = balance + 1 WHERE account_id = 1")
        assert mysql_errno(e) == ER_LOCK_WAIT_TIMEOUT
    finally:
        holder.rollback()
        holder.close()
        other.close()
    assert balance(db, 1) == Decimal("5000.00")


@pytest.mark.database
def test_DB_LCK_02_locking_one_row_does_not_block_a_different_row(db):
    holder = connect(autocommit=False)
    other = connect()
    try:
        run(holder, "SELECT * FROM accounts WHERE account_id = 1 FOR UPDATE")
        run(other, "SET SESSION innodb_lock_wait_timeout = 1")
        run(other, "UPDATE accounts SET balance = balance + 1 WHERE account_id = 2")
    finally:
        holder.rollback()
        holder.close()
        other.close()
    assert balance(db, 2) == Decimal("3001.00")


@pytest.mark.database
def test_DB_LCK_03_concurrent_deposits_lose_no_updates(db):
    """20 sessions each add 1.00 to the same account at the same time."""
    workers = 20
    errors = []

    def deposit():
        c = connect()
        try:
            run(c, "UPDATE accounts SET balance = balance + 1 WHERE account_id = 1")
        except Exception as exc:          # pragma: no cover - reported via assert below
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=deposit) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert balance(db, 1) == Decimal("5000.00") + workers
    assert audit_count(db, 1) == workers


@pytest.mark.database
def test_DB_LCK_04_concurrent_opposite_transfers_conserve_total_money(db):
    """Many transfers 1->2 and 2->1 at once, locking in a consistent order (lowest id
    first), like the API does. Nothing is lost and no deadlock occurs."""
    before = total_balance(db)
    results = []

    def transfer(src, dst):
        c = connect(autocommit=False)
        try:
            run(c, "SET SESSION innodb_lock_wait_timeout = 20")
            run(c, "SELECT * FROM accounts WHERE account_id IN (%s, %s) ORDER BY account_id FOR UPDATE",
                (src, dst))
            run(c, "UPDATE accounts SET balance = balance - 10 WHERE account_id = %s", (src,))
            run(c, "UPDATE accounts SET balance = balance + 10 WHERE account_id = %s", (dst,))
            c.commit()
            results.append("ok")
        except pymysql.MySQLError as exc:
            c.rollback()
            results.append(exc.args[0])
        finally:
            c.close()

    threads = []
    for i in range(10):
        pair = (1, 2) if i % 2 == 0 else (2, 1)
        threads.append(threading.Thread(target=transfer, args=pair))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["ok"] * 10
    assert total_balance(db) == before
    # 5 transfers each way of the same size cancel out
    assert balance(db, 1) == Decimal("5000.00")
    assert balance(db, 2) == Decimal("3000.00")


def _two_sessions(first_a, second_a, first_b, second_b):
    """Session A locks first_a then second_a; session B locks first_b then second_b.
    A pause after the first lock makes the lock orders overlap. Returns [result_a, result_b]."""
    results = [None, None]

    def session(idx, first, second):
        c = connect(autocommit=False)
        try:
            run(c, "SET SESSION innodb_lock_wait_timeout = 10")
            run(c, "SELECT * FROM accounts WHERE account_id = %s FOR UPDATE", (first,))
            time.sleep(0.5)
            run(c, "SELECT * FROM accounts WHERE account_id = %s FOR UPDATE", (second,))
            c.commit()
            results[idx] = "ok"
        except pymysql.MySQLError as exc:
            c.rollback()
            results[idx] = exc.args[0]
        finally:
            c.close()

    ta = threading.Thread(target=session, args=(0, first_a, second_a))
    tb = threading.Thread(target=session, args=(1, first_b, second_b))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    return results


@pytest.mark.database
def test_DB_LCK_05_opposite_lock_order_causes_a_deadlock(db):
    """Demonstrates the hazard the app avoids: A locks 1 then 2 while B locks 2 then 1.
    InnoDB must detect the deadlock and abort exactly one session."""
    results = _two_sessions(1, 2, 2, 1)
    assert sorted(map(str, results)) == sorted(["ok", str(ER_LOCK_DEADLOCK)])


@pytest.mark.database
def test_DB_LCK_06_same_lock_order_never_deadlocks(db):
    """The app's rule: always lock the lowest account_id first. Both sessions succeed."""
    results = _two_sessions(1, 2, 1, 2)
    assert results == ["ok", "ok"]

# ============================================================================
# db schema
# ============================================================================

TABLES = {"branches", "users", "accounts", "transactions", "loans", "audit_log"}


def _names(db, sql, params=None):
    return {list(r.values())[0] for r in rows(db, sql, params)}


@pytest.mark.database
def test_DB_SCH_01_all_six_tables_exist(db):
    found = _names(db, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                   (TEST_DB_NAME,))
    assert TABLES <= found


@pytest.mark.database
def test_DB_SCH_02_all_tables_use_innodb(db):
    engines = rows(db, "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                   (TEST_DB_NAME,))
    assert all(r["ENGINE"] == "InnoDB" for r in engines)   # needed for transactions and row locks


@pytest.mark.database
def test_DB_SCH_03_audit_trigger_exists_on_accounts(db):
    row = rows(db, "SELECT EVENT_MANIPULATION, ACTION_TIMING, EVENT_OBJECT_TABLE "
                   "FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = %s "
                   "AND TRIGGER_NAME = 'trg_account_balance_update'", (TEST_DB_NAME,))
    assert len(row) == 1
    assert (row[0]["EVENT_MANIPULATION"], row[0]["ACTION_TIMING"], row[0]["EVENT_OBJECT_TABLE"]) == \
           ("UPDATE", "AFTER", "accounts")


@pytest.mark.database
@pytest.mark.parametrize("index", ["idx_txn_from", "idx_txn_to", "idx_txn_created", "idx_accounts_user"])
def test_DB_SCH_04_expected_indexes_exist(db, index):
    assert scalar(db, "SELECT COUNT(*) FROM information_schema.STATISTICS "
                      "WHERE TABLE_SCHEMA = %s AND INDEX_NAME = %s", (TEST_DB_NAME, index)) >= 1


@pytest.mark.database
def test_DB_SCH_05_all_expected_check_constraints_exist(db):
    found = _names(db, "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                       "WHERE TABLE_SCHEMA = %s AND CONSTRAINT_TYPE = 'CHECK'", (TEST_DB_NAME,))
    expected = {"chk_balance_nonnegative", "chk_amount_positive", "chk_txn_shape",
                "chk_loan_amount_positive", "chk_loan_rate_nonneg", "chk_loan_tenure_positive"}
    assert expected <= found


@pytest.mark.database
def test_DB_SCH_06_money_columns_are_exact_decimals(db):
    cols = rows(db, "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s AND ((TABLE_NAME = 'accounts' AND COLUMN_NAME = 'balance') "
                    "OR (TABLE_NAME = 'transactions' AND COLUMN_NAME = 'amount'))", (TEST_DB_NAME,))
    assert len(cols) == 2
    assert all(c["COLUMN_TYPE"] == "decimal(15,2)" for c in cols)   # never FLOAT for money


@pytest.mark.database
def test_DB_SCH_07_email_and_ifsc_have_unique_indexes(db):
    unique = _names(db, "SELECT CONCAT(TABLE_NAME, '.', COLUMN_NAME) FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA = %s AND NON_UNIQUE = 0", (TEST_DB_NAME,))
    assert {"users.email", "branches.ifsc_code"} <= unique


@pytest.mark.database
def test_DB_SCH_08_seed_data_is_loaded(db):
    assert scalar(db, "SELECT COUNT(*) FROM users") == 3
    assert scalar(db, "SELECT COUNT(*) FROM branches") == 3
    assert scalar(db, "SELECT COUNT(*) FROM accounts") == 2
    assert scalar(db, "SELECT COUNT(*) FROM users WHERE role = 'admin'") == 1


@pytest.mark.database
def test_DB_SCH_09_passwords_are_stored_as_bcrypt_hashes(db):
    hashes = [r["password_hash"] for r in rows(db, "SELECT password_hash FROM users")]
    assert hashes and all(h.startswith("$2") and len(h) == 60 for h in hashes)
