"""Small helpers shared by all test files."""
import pymysql
from pymysql.cursors import DictCursor

import config

# MySQL error numbers used in assertions
ER_DUP_ENTRY = 1062
ER_BAD_NULL = 1048
ER_NO_REFERENCED_ROW = 1452      # child row: parent does not exist
ER_ROW_IS_REFERENCED = 1451      # parent row: children still exist
ER_LOCK_WAIT_TIMEOUT = 1205
ER_LOCK_DEADLOCK = 1213
ER_CHECK_VIOLATED = 3819
ER_DATA_TRUNCATED = 1265


def connect(database=config.TEST_DB_NAME, autocommit=True):
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=database,
        autocommit=autocommit,
        cursorclass=DictCursor,
    )


def run(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def rows(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def one(conn, sql, params=None):
    result = rows(conn, sql, params)
    return result[0] if result else None


def scalar(conn, sql, params=None):
    row = one(conn, sql, params)
    return None if row is None else next(iter(row.values()))


def balance(conn, account_id):
    return scalar(conn, "SELECT balance FROM accounts WHERE account_id = %s", (account_id,))


def total_balance(conn):
    return scalar(conn, "SELECT SUM(balance) FROM accounts")


def audit_count(conn, account_id=None):
    if account_id is None:
        return scalar(conn, "SELECT COUNT(*) FROM audit_log")
    return scalar(conn, "SELECT COUNT(*) FROM audit_log WHERE account_id = %s", (account_id,))


def make_user(conn, email, role="customer"):
    return run(
        conn,
        "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
        ("Test User", email, "x" * 60, role),
    )


def make_account(conn, user_id, balance=0, branch_id=1, status="active"):
    return run(
        conn,
        "INSERT INTO accounts (user_id, branch_id, balance, status) VALUES (%s, %s, %s, %s)",
        (user_id, branch_id, balance, status),
    )


def mysql_errno(excinfo):
    """Error number from a pytest.raises(pymysql.MySQLError) context.
    MariaDB (e.g. XAMPP) reports a failed CHECK as 4025 instead of MySQL's 3819; both are
    normalised to 3819 so the suite passes on either server."""
    code = excinfo.value.args[0]
    return ER_CHECK_VIOLATED if code == 4025 else code


def split_sql(text):
    """Split a .sql file into statements, honouring DELIMITER changes (for triggers)."""
    statements, buf, delim = [], [], ";"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            delim = stripped.split(None, 1)[1]
            continue
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        if stripped.endswith(delim):
            stmt = "\n".join(buf).rstrip()
            stmt = stmt[: -len(delim)].strip()
            if stmt:
                statements.append(stmt)
            buf = []
    return statements


def run_sql_file(conn, path):
    text = path.read_text(encoding="utf-8")
    for stmt in split_sql(text):
        if stmt.upper().startswith("USE "):
            continue  # we are already connected to the test DB
        run(conn, stmt)
