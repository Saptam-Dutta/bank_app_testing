"""UI testing (Playwright): admin panel and stored-XSS security checks (UI-xxx)."""
import re
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from helpers import balance, run, scalar

pytestmark = pytest.mark.ui

RUPEE = "₹"
XSS_IMG = '<img src=x onerror="window.__xss=1">'


def admin_tab(ui, name):
    ui.page.click(f".admin-tab-btn[data-tab={name}]")


# ------------------------------------------------------------------- admin
def test_UI_67_overview_cards_show_the_right_totals(ui):
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#statUsers")).to_have_text("3")
    expect(ui.page.locator("#statAccounts")).to_have_text("2")
    expect(ui.page.locator("#statTxns")).to_have_text("0")
    expect(ui.page.locator("#statBalance")).to_have_text(f"{RUPEE}8000.00")


def test_UI_68_users_tab_lists_every_user_without_password_data(ui):
    ui.login_as("admin@example.com")
    body = ui.page.locator("#usersBody")
    expect(body.locator("tr")).to_have_count(3)
    for text in ("Alice Johnson", "bob@example.com", "admin"):
        expect(body).to_contain_text(text)
    assert "$2b$" not in ui.page.content()


def test_UI_69_admin_tabs_show_one_panel_at_a_time(ui):
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#usersPanel")).to_be_visible()
    for name in ("accounts", "transactions", "auditlog"):
        admin_tab(ui, name)
        expect(ui.page.locator(f"#{name}Panel")).to_be_visible()
        expect(ui.page.locator(".admin-panel:visible")).to_have_count(1)
    expect(ui.page.locator("#usersPanel")).to_be_hidden()


def test_UI_70_accounts_tab_shows_owner_balance_status_and_actions(ui):
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    first = ui.page.locator("#accountsBody tr").nth(0)
    expect(first).to_contain_text("Alice Johnson (alice@example.com)")
    expect(first).to_contain_text(f"{RUPEE}5000.00")
    expect(first.locator(".badge")).to_have_text("active")
    expect(first.locator("button")).to_have_text(["Freeze", "Close"])     # no "Activate" while active


def test_UI_71_freezing_an_account_updates_the_page_and_blocks_the_customer(ui, db, api):
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='frozen']")
    first = ui.page.locator("#accountsBody tr").nth(0)
    expect(first.locator(".badge")).to_have_text("frozen")
    expect(first.locator("button")).to_have_text(["Activate", "Close"])
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "frozen"
    assert api.deposit(api.login("alice@example.com"), 1, 10).status_code == 400


def test_UI_72_activating_a_frozen_account_restores_it(ui, db):
    run(db, "UPDATE accounts SET status = 'frozen' WHERE account_id = 1")
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='active']")
    expect(ui.page.locator("#accountsBody tr").nth(0).locator(".badge")).to_have_text("active")
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


def test_UI_73_closing_an_account_that_still_has_money_shows_an_alert(ui, db):
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='closed']")
    assert ui.wait_dialog() == "Account must have zero balance before it can be closed"
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


def test_UI_74_closing_an_empty_account_works_and_removes_its_action_buttons(ui, db):
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='closed']")
    first = ui.page.locator("#accountsBody tr").nth(0)
    expect(first.locator(".badge")).to_have_text("closed")
    expect(first.locator("button")).to_have_text(["Activate", "Freeze"])


def test_UI_75_reopening_a_closed_account_is_refused_with_an_alert(ui, db):
    run(db, "UPDATE accounts SET balance = 0, status = 'closed' WHERE account_id = 1")
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='active']")
    assert ui.wait_dialog() == "A closed account cannot be changed"
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "closed"


def test_UI_76_transactions_tab_lists_activity_newest_first(ui, api):
    token = api.login("alice@example.com")
    api.deposit(token, 1, 11)
    api.withdraw(token, 1, 22)
    ui.login_as("admin@example.com")
    admin_tab(ui, "transactions")
    rows_ = ui.page.locator("#adminTxnsBody tr")
    expect(rows_).to_have_count(2)
    expect(rows_.nth(0)).to_contain_text("WITHDRAWAL")
    expect(rows_.nth(0)).to_contain_text(f"{RUPEE}22.00")
    expect(rows_.nth(1)).to_contain_text("DEPOSIT")
    expect(ui.page.locator("#statTxns")).to_have_text("2")


def test_UI_77_audit_log_tab_shows_balance_changes_with_owner(ui, api):
    api.deposit(api.login("alice@example.com"), 1, 100)
    ui.login_as("admin@example.com")
    admin_tab(ui, "auditlog")
    row = ui.page.locator("#auditBody tr")
    expect(row).to_have_count(1)
    for text in ("Alice Johnson", "BALANCE_UPDATE", f"{RUPEE}5000.00", f"{RUPEE}5100.00"):
        expect(row).to_contain_text(text)


def test_UI_78_overview_total_balance_updates_after_a_customer_deposit(ui, api):
    api.deposit(api.login("bob@example.com"), 2, 500)
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#statBalance")).to_have_text(f"{RUPEE}8500.00")


def test_UI_79_admin_logout_returns_to_login(ui):
    ui.login_as("admin@example.com")
    ui.page.click("#logoutBtn")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))
    ui.goto("/admin.html")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


# ----------------------------------------------------------- XSS (security)
def test_UI_80_script_in_a_users_name_does_not_run_in_the_admin_panel(ui, api):
    """Stored XSS: a customer registers with HTML in their name; the admin opens the Users tab.
    The text must be shown literally, never executed."""
    api.post("/api/auth/register", json={"name": XSS_IMG, "email": "xss@example.com", "password": "Passw0rd!"})
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#usersBody tr")).to_have_count(4)
    ui.page.wait_for_timeout(600)
    assert ui.page.evaluate("window.__xss") is None, "script from a user's name ran in the admin's browser"
    expect(ui.page.locator("#usersBody")).to_contain_text("<img src=x")      # shown as plain text


def test_UI_81_script_in_a_transfer_note_does_not_run_for_the_receiver(ui, api):
    """Alice sends Bob a transfer whose note contains HTML; Bob opens his statement."""
    api.transfer(api.login("alice@example.com"), 1, 2, 5, description=XSS_IMG)
    ui.login_as("bob@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '2')")
    ui.goto("/account-details.html")
    expect(ui.page.locator("#statementBody tr")).to_have_count(1)
    ui.page.wait_for_timeout(600)
    assert ui.page.evaluate("window.__xss") is None, "script from a transfer note ran in the receiver's browser"
    expect(ui.page.locator("#statementBody")).to_contain_text("<img src=x")


def test_UI_82_script_in_an_email_cannot_run_in_the_admin_panel(ui, db):
    """Same check for the email column (inserted directly, since the API validates email format)."""
    run(db, "UPDATE users SET email = %s WHERE user_id = 2", ('"><img src=x onerror="window.__xss=1">',))
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#usersBody tr")).to_have_count(3)
    ui.page.wait_for_timeout(600)
    assert ui.page.evaluate("window.__xss") is None


def test_UI_83_welcome_message_shows_html_in_a_name_as_plain_text(ui, api):
    api.post("/api/auth/register", json={"name": "<b>Bold</b>", "email": "b@example.com", "password": "Passw0rd!"})
    ui.login_as("b@example.com", password="Passw0rd!")
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Hi, <b>Bold</b>")
    assert ui.page.locator("#welcomeMsg b").count() == 0
