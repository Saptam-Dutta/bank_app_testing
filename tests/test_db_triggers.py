"""Database testing: audit trigger trg_account_balance_update (DB-TRG-xx)."""
from decimal import Decimal

import pymysql
import pytest

from helpers import audit_count, connect, make_account, make_user, mysql_errno, one, rows, run, ER_CHECK_VIOLATED

pytestmark = pytest.mark.database


def test_DB_TRG_01_balance_change_writes_one_audit_row(db):
    run(db, "UPDATE accounts SET balance = 5500 WHERE account_id = 1")
    log = rows(db, "SELECT * FROM audit_log WHERE account_id = 1")
    assert len(log) == 1
    assert log[0]["action"] == "BALANCE_UPDATE"


def test_DB_TRG_02_audit_row_stores_correct_old_and_new_balance(db):
    run(db, "UPDATE accounts SET balance = balance - 1250.75 WHERE account_id = 1")
    log = one(db, "SELECT * FROM audit_log WHERE account_id = 1")
    assert log["old_balance"] == Decimal("5000.00")
    assert log["new_balance"] == Decimal("3749.25")


def test_DB_TRG_03_audit_row_has_a_timestamp(db):
    run(db, "UPDATE accounts SET balance = 1 WHERE account_id = 1")
    assert one(db, "SELECT changed_at FROM audit_log")["changed_at"] is not None


def test_DB_TRG_04_status_change_alone_writes_no_audit_row(db):
    run(db, "UPDATE accounts SET status = 'frozen' WHERE account_id = 1")
    assert audit_count(db) == 0


def test_DB_TRG_05_update_to_same_balance_writes_no_audit_row(db):
    run(db, "UPDATE accounts SET balance = 5000 WHERE account_id = 1")
    assert audit_count(db) == 0


def test_DB_TRG_06_inserting_an_account_writes_no_audit_row(db):
    """The trigger is AFTER UPDATE only, so opening a new account is not logged."""
    make_account(db, 1, balance=100)
    assert audit_count(db) == 0


def test_DB_TRG_07_multi_row_update_writes_one_audit_row_per_account(db):
    run(db, "UPDATE accounts SET balance = balance + 10")
    assert audit_count(db, 1) == 1
    assert audit_count(db, 2) == 1
    assert audit_count(db) == 2


def test_DB_TRG_08_each_change_gets_its_own_audit_row_in_order(db):
    for amount in (100, 200, 300):
        run(db, "UPDATE accounts SET balance = %s WHERE account_id = 1", (amount,))
    log = rows(db, "SELECT old_balance, new_balance FROM audit_log WHERE account_id = 1 ORDER BY log_id")
    assert [(r["old_balance"], r["new_balance"]) for r in log] == [
        (Decimal("5000.00"), Decimal("100.00")),
        (Decimal("100.00"), Decimal("200.00")),
        (Decimal("200.00"), Decimal("300.00")),
    ]


def test_DB_TRG_09_rejected_update_leaves_no_audit_row(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET balance = -1 WHERE account_id = 1")
    assert mysql_errno(e) == ER_CHECK_VIOLATED
    assert audit_count(db) == 0


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


def test_DB_TRG_11_committed_change_keeps_its_audit_row(db):
    conn = connect(autocommit=False)
    try:
        run(conn, "UPDATE accounts SET balance = 1 WHERE account_id = 1")
        conn.commit()
    finally:
        conn.close()
    assert audit_count(db, 1) == 1


def test_DB_TRG_12_audit_entries_exist_for_both_sides_of_a_transfer(db):
    """What the API does for a transfer: debit one account, credit the other."""
    run(db, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(db, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    assert audit_count(db, 1) == 1 and audit_count(db, 2) == 1
