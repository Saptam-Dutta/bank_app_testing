"""Database testing: transactions, atomicity and rollback (DB-TXN-xx)."""
from decimal import Decimal

import pymysql
import pytest

from helpers import ER_CHECK_VIOLATED, audit_count, balance, connect, mysql_errno, run, scalar, total_balance

pytestmark = pytest.mark.database


@pytest.fixture
def conn():
    c = connect(autocommit=False)
    yield c
    c.rollback()
    c.close()


def test_DB_TXN_01_committed_transfer_persists(db, conn):
    run(conn, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    conn.commit()
    assert balance(db, 1) == Decimal("4500.00")
    assert balance(db, 2) == Decimal("3500.00")


def test_DB_TXN_02_rolled_back_transfer_changes_nothing(db, conn):
    run(conn, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    conn.rollback()
    assert balance(db, 1) == Decimal("5000.00")
    assert balance(db, 2) == Decimal("3000.00")


def test_DB_TXN_03_uncommitted_changes_are_invisible_to_other_sessions(db, conn):
    run(conn, "UPDATE accounts SET balance = 1 WHERE account_id = 1")
    assert balance(db, 1) == Decimal("5000.00")      # isolation: no dirty read
    conn.rollback()


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


def test_DB_TXN_05_rollback_also_removes_the_transaction_record(db, conn):
    run(conn, "INSERT INTO transactions (from_account_id, to_account_id, amount, type, status) "
              "VALUES (1, 2, 500, 'transfer', 'success')")
    conn.rollback()
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 0


def test_DB_TXN_06_rollback_removes_audit_rows_as_well(db, conn):
    run(conn, "UPDATE accounts SET balance = balance - 500 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 500 WHERE account_id = 2")
    conn.rollback()
    assert audit_count(db) == 0


def test_DB_TXN_07_total_money_is_conserved_across_a_committed_transfer(db, conn):
    before = total_balance(db)
    run(conn, "UPDATE accounts SET balance = balance - 1234.56 WHERE account_id = 1")
    run(conn, "UPDATE accounts SET balance = balance + 1234.56 WHERE account_id = 2")
    conn.commit()
    assert total_balance(db) == before


def test_DB_TXN_08_a_failed_statement_does_not_commit_earlier_work_automatically(db, conn):
    """A statement error inside a transaction must not silently commit what came before."""
    run(conn, "UPDATE accounts SET balance = balance + 100 WHERE account_id = 2")
    with pytest.raises(pymysql.MySQLError):
        run(conn, "UPDATE accounts SET balance = -5 WHERE account_id = 1")
    conn.rollback()
    assert balance(db, 2) == Decimal("3000.00")
