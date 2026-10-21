"""Database testing: schema structure checks (DB-SCH-xx)."""
import pytest

from config import TEST_DB_NAME
from helpers import rows, scalar

pytestmark = pytest.mark.database

TABLES = {"branches", "users", "accounts", "transactions", "loans", "audit_log"}


def _names(db, sql, params=None):
    return {list(r.values())[0] for r in rows(db, sql, params)}


def test_DB_SCH_01_all_six_tables_exist(db):
    found = _names(db, "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                   (TEST_DB_NAME,))
    assert TABLES <= found


def test_DB_SCH_02_all_tables_use_innodb(db):
    engines = rows(db, "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                   (TEST_DB_NAME,))
    assert all(r["ENGINE"] == "InnoDB" for r in engines)   # needed for transactions and row locks


def test_DB_SCH_03_audit_trigger_exists_on_accounts(db):
    row = rows(db, "SELECT EVENT_MANIPULATION, ACTION_TIMING, EVENT_OBJECT_TABLE "
                   "FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = %s "
                   "AND TRIGGER_NAME = 'trg_account_balance_update'", (TEST_DB_NAME,))
    assert len(row) == 1
    assert (row[0]["EVENT_MANIPULATION"], row[0]["ACTION_TIMING"], row[0]["EVENT_OBJECT_TABLE"]) == \
           ("UPDATE", "AFTER", "accounts")


@pytest.mark.parametrize("index", ["idx_txn_from", "idx_txn_to", "idx_txn_created", "idx_accounts_user"])
def test_DB_SCH_04_expected_indexes_exist(db, index):
    assert scalar(db, "SELECT COUNT(*) FROM information_schema.STATISTICS "
                      "WHERE TABLE_SCHEMA = %s AND INDEX_NAME = %s", (TEST_DB_NAME, index)) >= 1


def test_DB_SCH_05_all_expected_check_constraints_exist(db):
    found = _names(db, "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                       "WHERE TABLE_SCHEMA = %s AND CONSTRAINT_TYPE = 'CHECK'", (TEST_DB_NAME,))
    expected = {"chk_balance_nonnegative", "chk_amount_positive", "chk_txn_shape",
                "chk_loan_amount_positive", "chk_loan_rate_nonneg", "chk_loan_tenure_positive"}
    assert expected <= found


def test_DB_SCH_06_money_columns_are_exact_decimals(db):
    cols = rows(db, "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s AND ((TABLE_NAME = 'accounts' AND COLUMN_NAME = 'balance') "
                    "OR (TABLE_NAME = 'transactions' AND COLUMN_NAME = 'amount'))", (TEST_DB_NAME,))
    assert len(cols) == 2
    assert all(c["COLUMN_TYPE"] == "decimal(15,2)" for c in cols)   # never FLOAT for money


def test_DB_SCH_07_email_and_ifsc_have_unique_indexes(db):
    unique = _names(db, "SELECT CONCAT(TABLE_NAME, '.', COLUMN_NAME) FROM information_schema.STATISTICS "
                        "WHERE TABLE_SCHEMA = %s AND NON_UNIQUE = 0", (TEST_DB_NAME,))
    assert {"users.email", "branches.ifsc_code"} <= unique


def test_DB_SCH_08_seed_data_is_loaded(db):
    assert scalar(db, "SELECT COUNT(*) FROM users") == 3
    assert scalar(db, "SELECT COUNT(*) FROM branches") == 3
    assert scalar(db, "SELECT COUNT(*) FROM accounts") == 2
    assert scalar(db, "SELECT COUNT(*) FROM users WHERE role = 'admin'") == 1


def test_DB_SCH_09_passwords_are_stored_as_bcrypt_hashes(db):
    hashes = [r["password_hash"] for r in rows(db, "SELECT password_hash FROM users")]
    assert hashes and all(h.startswith("$2") and len(h) == 60 for h in hashes)
