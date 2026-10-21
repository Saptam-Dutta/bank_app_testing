"""Database testing: referential integrity and cascades (DB-REF-xx)."""
import pymysql
import pytest

from helpers import (ER_NO_REFERENCED_ROW, ER_ROW_IS_REFERENCED, make_account, make_user,
                     mysql_errno, run, scalar)

pytestmark = pytest.mark.database


def test_DB_REF_01_account_needs_an_existing_user(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_account(db, user_id=9999)
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


def test_DB_REF_02_account_needs_an_existing_branch(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_account(db, user_id=1, branch_id=9999)
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


def test_DB_REF_03_transaction_source_account_must_exist(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (9999, NULL, 10, 'withdrawal')")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


def test_DB_REF_04_transaction_destination_account_must_exist(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (NULL, 9999, 10, 'deposit')")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


def test_DB_REF_05_loan_needs_an_existing_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (9999, 1000, 8, 12)")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW


def test_DB_REF_06_deleting_a_user_cascades_to_their_accounts(db):
    uid = make_user(db, "temp@example.com")
    acc = make_account(db, uid)
    run(db, "DELETE FROM users WHERE user_id = %s", (uid,))
    assert scalar(db, "SELECT COUNT(*) FROM accounts WHERE account_id = %s", (acc,)) == 0


def test_DB_REF_07_deleting_an_account_cascades_to_its_loans(db):
    uid = make_user(db, "temp@example.com")
    acc = make_account(db, uid)
    run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
            "VALUES (%s, 1000, 8, 12)", (acc,))
    run(db, "DELETE FROM accounts WHERE account_id = %s", (acc,))
    assert scalar(db, "SELECT COUNT(*) FROM loans WHERE account_id = %s", (acc,)) == 0


def test_DB_REF_08_user_with_transaction_history_cannot_be_deleted(db):
    """Money history must not vanish: transactions reference accounts without CASCADE."""
    run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
            "VALUES (1, 2, 10, 'transfer')")
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "DELETE FROM users WHERE user_id = 1")
    assert mysql_errno(e) == ER_ROW_IS_REFERENCED
    assert scalar(db, "SELECT COUNT(*) FROM accounts WHERE user_id = 1") == 1


def test_DB_REF_09_branch_with_accounts_cannot_be_deleted(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "DELETE FROM branches WHERE branch_id = 1")
    assert mysql_errno(e) == ER_ROW_IS_REFERENCED


def test_DB_REF_10_account_with_audit_history_cannot_be_deleted(db):
    """Hardening fix: audit_log used to ON DELETE CASCADE, so deleting an account
    silently erased its audit trail. It must now be blocked."""
    run(db, "UPDATE accounts SET balance = balance + 1 WHERE account_id = 1")
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "DELETE FROM accounts WHERE account_id = 1")
    assert mysql_errno(e) == ER_ROW_IS_REFERENCED
    assert scalar(db, "SELECT COUNT(*) FROM audit_log WHERE account_id = 1") == 1


def test_DB_REF_11_audit_row_needs_an_existing_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO audit_log (account_id, action, old_balance, new_balance) "
                "VALUES (9999, 'X', 0, 1)")
    assert mysql_errno(e) == ER_NO_REFERENCED_ROW
