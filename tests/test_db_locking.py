"""Database testing: row-level locking, concurrency and deadlocks (DB-LCK-xx)."""
import threading
import time
from decimal import Decimal

import pymysql
import pytest

from helpers import (ER_LOCK_DEADLOCK, ER_LOCK_WAIT_TIMEOUT, audit_count, balance, connect,
                     mysql_errno, run, total_balance)

pytestmark = pytest.mark.database


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


def test_DB_LCK_05_opposite_lock_order_causes_a_deadlock(db):
    """Demonstrates the hazard the app avoids: A locks 1 then 2 while B locks 2 then 1.
    InnoDB must detect the deadlock and abort exactly one session."""
    results = _two_sessions(1, 2, 2, 1)
    assert sorted(map(str, results)) == sorted(["ok", str(ER_LOCK_DEADLOCK)])


def test_DB_LCK_06_same_lock_order_never_deadlocks(db):
    """The app's rule: always lock the lowest account_id first. Both sessions succeed."""
    results = _two_sessions(1, 2, 1, 2)
    assert results == ["ok", "ok"]
