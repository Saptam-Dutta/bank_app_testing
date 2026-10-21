"""Database testing: constraint validation (DB-CON-xx)."""
import pymysql
import pytest

from helpers import (ER_BAD_NULL, ER_CHECK_VIOLATED, ER_DATA_TRUNCATED, ER_DUP_ENTRY,
                     balance, make_account, make_user, mysql_errno, one, run)

pytestmark = pytest.mark.database


def test_DB_CON_01_balance_cannot_be_updated_below_zero(db):
    """CHECK (balance >= 0): overdrawing an account directly in SQL is rejected."""
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET balance = -0.01 WHERE account_id = 1")
    assert mysql_errno(e) == ER_CHECK_VIOLATED
    assert balance(db, 1) == 5000


def test_DB_CON_02_withdrawing_more_than_balance_is_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET balance = balance - 5000.01 WHERE account_id = 1")
    assert mysql_errno(e) == ER_CHECK_VIOLATED
    assert balance(db, 1) == 5000


def test_DB_CON_03_account_cannot_be_inserted_with_negative_balance(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_account(db, 1, balance=-10)
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_04_balance_of_exactly_zero_is_allowed(db):
    """Boundary value: 0.00 is valid."""
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    assert balance(db, 1) == 0


def test_DB_CON_05_transaction_amount_zero_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (NULL, 1, 0, 'deposit')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_06_transaction_amount_negative_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (NULL, 1, -50, 'deposit')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_07_smallest_valid_amount_is_accepted(db):
    """Boundary value: 0.01 is valid."""
    run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
            "VALUES (NULL, 1, 0.01, 'deposit')")
    assert one(db, "SELECT COUNT(*) AS c FROM transactions")["c"] == 1


def test_DB_CON_08_duplicate_email_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        make_user(db, "alice@example.com")
    assert mysql_errno(e) == ER_DUP_ENTRY


def test_DB_CON_09_duplicate_ifsc_code_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO branches (branch_name, ifsc_code) VALUES ('Clone', 'BANK0001234')")
    assert mysql_errno(e) == ER_DUP_ENTRY


def test_DB_CON_10_user_name_cannot_be_null(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO users (name, email, password_hash) VALUES (NULL, 'n@x.com', 'h')")
    assert mysql_errno(e) == ER_BAD_NULL


def test_DB_CON_11_password_hash_cannot_be_null(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO users (name, email, password_hash) VALUES ('N', 'n@x.com', NULL)")
    assert mysql_errno(e) == ER_BAD_NULL


def test_DB_CON_12_invalid_role_value_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO users (name, email, password_hash, role) "
                "VALUES ('N', 'n@x.com', 'h', 'superuser')")
    assert mysql_errno(e) == ER_DATA_TRUNCATED


def test_DB_CON_13_invalid_account_status_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "UPDATE accounts SET status = 'suspended' WHERE account_id = 1")
    assert mysql_errno(e) == ER_DATA_TRUNCATED


def test_DB_CON_14_invalid_transaction_type_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 2, 10, 'refund')")
    assert mysql_errno(e) == ER_DATA_TRUNCATED


def test_DB_CON_15_loan_amount_must_be_positive(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (1, -1000, 8.5, 12)")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_16_loan_tenure_must_be_positive(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (1, 1000, 8.5, 0)")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_17_loan_interest_rate_cannot_be_negative(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
                "VALUES (1, 1000, -1, 12)")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_18_valid_loan_is_accepted(db):
    """Positive control: a sensible loan row is stored with status 'pending'."""
    run(db, "INSERT INTO loans (account_id, amount, interest_rate, tenure_months) "
            "VALUES (1, 100000, 8.5, 24)")
    assert one(db, "SELECT status FROM loans")["status"] == "pending"


def test_DB_CON_19_deposit_must_not_have_a_source_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 2, 10, 'deposit')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_20_withdrawal_must_not_have_a_destination_account(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 2, 10, 'withdrawal')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_21_transfer_to_same_account_rejected(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, 1, 10, 'transfer')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_22_transfer_requires_both_accounts(db):
    with pytest.raises(pymysql.MySQLError) as e:
        run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
                "VALUES (1, NULL, 10, 'transfer')")
    assert mysql_errno(e) == ER_CHECK_VIOLATED


def test_DB_CON_23_valid_transfer_row_is_accepted(db):
    """Positive control for the shape constraint."""
    run(db, "INSERT INTO transactions (from_account_id, to_account_id, amount, type) "
            "VALUES (1, 2, 10, 'transfer')")
    assert one(db, "SELECT COUNT(*) AS c FROM transactions")["c"] == 1
