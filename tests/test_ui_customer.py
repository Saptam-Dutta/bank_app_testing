"""UI testing (Playwright): customer dashboard, statement page and profile (UI-xxx)."""
import re
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from helpers import balance, one, run, scalar

pytestmark = pytest.mark.ui

MINUS = "−"      # the minus sign the statement page uses
RUPEE = "₹"


def submit(ui, form):
    ui.page.click(f"#{form}Form button[type=submit]")


def tab(ui, name):
    ui.page.click(f".tab-btn[data-tab={name}]")


def card_balance(ui, index=0):
    return ui.page.locator(".account-card .balance").nth(index)


# ---------------------------------------------------------------- accounts
def test_UI_34_dashboard_lists_my_account_with_balance_status_and_branch(ui):
    ui.login_as("alice@example.com")
    card = ui.page.locator(".account-card")
    expect(card).to_have_count(1)
    expect(card).to_contain_text("Account #1")
    expect(card).to_contain_text("SAVINGS")
    expect(card).to_contain_text("Main Street Branch")
    expect(card.locator(".badge")).to_have_text("active")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}5000.00")


def test_UI_35_dashboard_shows_only_the_logged_in_users_accounts(ui):
    ui.login_as("bob@example.com")
    expect(ui.page.locator(".account-card")).to_have_count(1)
    expect(ui.page.locator(".account-card")).to_contain_text("Account #2")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}3000.00")


def test_UI_36_user_without_accounts_sees_a_friendly_message(ui, api):
    api.post("/api/auth/register", json={"name": "New Person", "email": "new@example.com", "password": "Passw0rd!"})
    ui.login_as("new@example.com", password="Passw0rd!")
    expect(ui.page.locator("#accountsList")).to_contain_text("No accounts yet")


def test_UI_37_account_dropdowns_are_filled_with_my_accounts(ui):
    ui.login_as("alice@example.com")
    for select in ("#depositAccount", "#withdrawAccount", "#transferFrom"):
        expect(ui.page.locator(f"{select} option")).to_have_count(1)
        expect(ui.page.locator(f"{select} option")).to_contain_text(f"Account #1 (savings) - {RUPEE}5000.00")


def test_UI_38_branch_dropdown_lists_all_branches_with_ifsc(ui):
    ui.login_as("alice@example.com")
    options = ui.page.locator("#branchSelect option")
    expect(options).to_have_count(3)
    texts = options.all_inner_texts()
    assert "Main Street Branch (BANK0001234)" in texts and all("BANK000" in t for t in texts)


def test_UI_39_open_new_account_form_toggles(ui):
    ui.login_as("alice@example.com")
    expect(ui.page.locator("#newAccountSection")).to_be_hidden()
    ui.page.click("#newAccountBtn")
    expect(ui.page.locator("#newAccountSection")).to_be_visible()
    ui.page.click("#newAccountBtn")
    expect(ui.page.locator("#newAccountSection")).to_be_hidden()


def test_UI_40_opening_a_new_account_adds_it_to_the_list(ui, db):
    ui.login_as("alice@example.com")
    ui.page.click("#newAccountBtn")
    ui.page.select_option("#accountType", "current")
    ui.page.select_option("#branchSelect", index=1)
    submit(ui, "newAccount")
    expect(ui.page.locator(".account-card")).to_have_count(2)
    expect(ui.page.locator("#newAccountSection")).to_be_hidden()
    assert one(db, "SELECT account_type, balance FROM accounts WHERE account_id = 3") == \
           {"account_type": "current", "balance": Decimal("0.00")}
    expect(ui.page.locator("#depositAccount option")).to_have_count(2)


# ------------------------------------------------------------ transactions
def test_UI_41_deposit_updates_the_balance_on_screen_and_in_the_database(ui, db):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", "250.50")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnSuccess")).to_have_text("Deposit successful!")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}5250.50")
    assert balance(db, 1) == Decimal("5250.50")
    expect(ui.page.locator("#depositAmount")).to_have_value("")      # form reset


def test_UI_42_withdrawal_updates_the_balance(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "withdraw")
    ui.page.fill("#withdrawAmount", "1000")
    submit(ui, "withdraw")
    expect(ui.page.locator("#txnSuccess")).to_have_text("Withdrawal successful!")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}4000.00")
    assert balance(db, 1) == 4000


def test_UI_43_transfer_moves_money_and_saves_the_note(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "transfer")
    ui.page.fill("#transferTo", "2")
    ui.page.fill("#transferAmount", "500")
    ui.page.fill("#transferDesc", "Rent")
    submit(ui, "transfer")
    expect(ui.page.locator("#txnSuccess")).to_have_text("Transfer successful!")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}4500.00")
    assert balance(db, 2) == 3500
    assert scalar(db, "SELECT description FROM transactions") == "Rent"


def test_UI_44_withdrawing_more_than_the_balance_shows_the_server_error(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "withdraw")
    ui.page.fill("#withdrawAmount", "99999")
    submit(ui, "withdraw")
    expect(ui.page.locator("#txnError")).to_have_text("Insufficient balance")
    assert balance(db, 1) == 5000


def test_UI_45_transfer_to_the_same_account_is_refused_on_screen(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "transfer")
    ui.page.fill("#transferTo", "1")
    ui.page.fill("#transferAmount", "10")
    submit(ui, "transfer")
    expect(ui.page.locator("#txnError")).to_have_text("Cannot transfer to the same account.")
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 0


def test_UI_46_transfer_to_a_nonexistent_account_shows_the_server_error(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "transfer")
    ui.page.fill("#transferTo", "99999")
    ui.page.fill("#transferAmount", "10")
    submit(ui, "transfer")
    expect(ui.page.locator("#txnError")).to_have_text("Destination account not found")
    assert balance(db, 1) == 5000


@pytest.mark.parametrize("amount", ["0", "-5", "10.999", "0.001"])
def test_UI_47_invalid_deposit_amounts_are_blocked_by_the_browser(ui, db, amount):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", amount)
    submit(ui, "deposit")
    assert ui.valid("#depositForm") is False
    expect(ui.page.locator("#txnSuccess")).to_be_hidden()
    assert balance(db, 1) == 5000


def test_UI_48_empty_amount_is_blocked_by_the_browser(ui):
    ui.login_as("alice@example.com")
    submit(ui, "deposit")
    assert ui.valid("#depositForm") is False


def test_UI_49_transaction_tabs_show_only_the_selected_form(ui):
    ui.login_as("alice@example.com")
    expect(ui.page.locator("#depositForm")).to_be_visible()
    expect(ui.page.locator("#withdrawForm")).to_be_hidden()
    tab(ui, "withdraw")
    expect(ui.page.locator("#withdrawForm")).to_be_visible()
    expect(ui.page.locator("#depositForm")).to_be_hidden()
    tab(ui, "transfer")
    expect(ui.page.locator("#transferForm")).to_be_visible()
    expect(ui.page.locator(".tab-btn.active")).to_have_text("Transfer")


def test_UI_50_switching_tab_clears_the_previous_message(ui):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", "10")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnSuccess")).to_be_visible()
    tab(ui, "withdraw")
    expect(ui.page.locator("#txnSuccess")).to_be_hidden()


def test_UI_51_frozen_account_cannot_receive_a_deposit(ui, db):
    run(db, "UPDATE accounts SET status = 'frozen' WHERE account_id = 1")
    ui.login_as("alice@example.com")
    expect(ui.page.locator(".account-card .badge")).to_have_text("frozen")
    ui.page.fill("#depositAmount", "10")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnError")).to_have_text("Account is not active")
    assert balance(db, 1) == 5000


def test_UI_52_overflowing_deposit_shows_a_clear_error(ui, db):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", "9999999999999.99")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnError")).to_contain_text("maximum")
    assert balance(db, 1) == 5000


# --------------------------------------------------------------- statement
def test_UI_53_view_statement_link_opens_the_account_details_page(ui):
    ui.login_as("alice@example.com")
    ui.page.click(".view-statement-link")
    expect(ui.page).to_have_url(re.compile(r"/account-details\.html$"))
    expect(ui.page.locator("#accountTitle")).to_have_text("Account #1")


def test_UI_54_account_details_shows_summary_and_balance(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
    ui.goto("/account-details.html")
    expect(ui.page.locator("#accountMeta")).to_have_text("SAVINGS — Main Street Branch (BANK0001234)")
    expect(ui.page.locator("#accountStatusBadge")).to_have_text("active")
    expect(ui.page.locator("#accountBalance")).to_have_text(f"{RUPEE}5000.00")


def test_UI_55_statement_rows_totals_and_signs_after_activity(ui, api):
    token = api.login("alice@example.com")
    api.deposit(token, 1, 100)
    api.withdraw(token, 1, 30)
    api.transfer(token, 1, 2, 20)
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
    ui.goto("/account-details.html")
    rows_ = ui.page.locator("#statementBody tr")
    expect(rows_).to_have_count(3)
    expect(rows_.nth(0)).to_contain_text("TRANSFER")
    expect(rows_.nth(0)).to_contain_text("To Account #2")
    expect(rows_.nth(0)).to_contain_text(f"{MINUS}{RUPEE}20.00")
    expect(rows_.nth(1)).to_contain_text(f"{MINUS}{RUPEE}30.00")
    expect(rows_.nth(2)).to_contain_text(f"+{RUPEE}100.00")
    expect(ui.page.locator("#totalDeposited")).to_have_text(f"{RUPEE}100.00")
    expect(ui.page.locator("#totalWithdrawn")).to_have_text(f"{RUPEE}50.00")
    expect(ui.page.locator("#txnCount")).to_have_text("3")
    expect(ui.page.locator("#accountBalance")).to_have_text(f"{RUPEE}5050.00")     # 5000 + 100 - 30 - 20


def test_UI_56_receiver_sees_an_incoming_transfer_as_a_credit(ui, api):
    api.transfer(api.login("alice@example.com"), 1, 2, 75, description="Thanks")
    ui.login_as("bob@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '2')")
    ui.goto("/account-details.html")
    row = ui.page.locator("#statementBody tr")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("From Account #1")
    expect(row).to_contain_text(f"+{RUPEE}75.00")
    expect(row).to_contain_text("Thanks")


def test_UI_57_account_without_activity_shows_no_transactions_message(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
    ui.goto("/account-details.html")
    expect(ui.page.locator("#statementBody")).to_contain_text("No transactions yet.")
    expect(ui.page.locator("#txnCount")).to_have_text("0")


def test_UI_58_account_details_without_a_selected_account_shows_not_found(ui):
    ui.login_as("alice@example.com", "/account-details.html")
    expect(ui.page.locator("#notFoundBox")).to_be_visible()
    expect(ui.page.locator("#accountContent")).to_be_hidden()


def test_UI_59_someone_elses_account_id_in_session_storage_shows_not_found(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '2')")
    ui.goto("/account-details.html")
    expect(ui.page.locator("#notFoundBox")).to_be_visible()
    expect(ui.page.locator("#accountBalance")).not_to_contain_text("3000")


def test_UI_60_back_link_returns_to_the_dashboard(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
    ui.goto("/account-details.html")
    ui.page.click("text=Back to Dashboard")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))


# ----------------------------------------------------------------- profile
def test_UI_61_profile_form_is_prefilled_and_read_only_fields_are_disabled(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    expect(ui.page.locator("#email")).to_have_value("alice@example.com")
    expect(ui.page.locator("#phone")).to_have_value("9876543210")
    expect(ui.page.locator("#role")).to_have_value("customer")
    for field in ("#email", "#role", "#createdAt"):
        expect(ui.page.locator(field)).to_be_disabled()
    assert ui.page.input_value("#createdAt") != ""


def test_UI_62_profile_update_is_saved_shown_and_persists_after_reload(ui, db):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    ui.page.fill("#name", "Alice Updated")
    ui.page.fill("#phone", "9000000001")
    ui.page.click("#profileForm button[type=submit]")
    expect(ui.page.locator("#successMsg")).to_have_text("Profile updated successfully!")
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Hi, Alice Updated")
    ui.page.reload()
    expect(ui.page.locator("#name")).to_have_value("Alice Updated")
    assert one(db, "SELECT name, phone FROM users WHERE user_id = 1") == {"name": "Alice Updated", "phone": "9000000001"}


def test_UI_63_invalid_phone_on_profile_shows_the_server_error(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    ui.page.fill("#phone", "abc")
    ui.page.click("#profileForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Phone must be 7 to 15 digits")


def test_UI_64_empty_name_on_profile_is_blocked_by_the_browser(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    ui.page.fill("#name", "")
    ui.page.click("#profileForm button[type=submit]")
    assert ui.valid("#profileForm") is False


def test_UI_65_overlong_name_on_profile_shows_the_server_error(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    ui.page.fill("#name", "N" * 101)
    ui.page.click("#profileForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Name must be at most 100 characters")


def test_UI_66_navbar_links_move_between_dashboard_and_profile(ui):
    ui.login_as("alice@example.com")
    ui.page.click(".nav-links a[href='profile.html']")
    expect(ui.page).to_have_url(re.compile(r"/profile\.html$"))
    ui.page.click(".nav-links a[href='dashboard.html']")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))
