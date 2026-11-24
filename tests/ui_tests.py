"""UI testing with Playwright: public pages, customer screens, admin panel (UI-xxx).

Merged from: test_ui_public.py, test_ui_customer.py, test_ui_admin.py.
"""
import pytest
import re
from decimal import Decimal
from helpers import balance, one, rows, run, scalar
from playwright.sync_api import expect


# ============================================================================
# ui public
# ============================================================================

NEW = {"name": "Carol White", "email": "carol@example.com", "phone": "9123456780", "password": "Secret123!"}


def fill_register(ui, **overrides):
    data = {**NEW, **overrides}
    ui.goto("/register.html")
    ui.page.fill("#name", data["name"])
    ui.page.fill("#email", data["email"])
    ui.page.fill("#phone", data["phone"])
    ui.page.fill("#password", data["password"])
    return data


# ----------------------------------------------------------------- landing
@pytest.mark.ui
def test_UI_01_landing_page_shows_headline_and_three_feature_cards(ui):
    ui.goto("/index.html")
    expect(ui.page.locator("h1")).to_have_text("Banking, made simple.")
    expect(ui.page.locator(".feature-card")).to_have_count(3)


@pytest.mark.ui
def test_UI_02_get_started_button_opens_registration(ui):
    ui.goto("/index.html")
    ui.page.click("text=Get Started")
    expect(ui.page).to_have_url(re.compile(r"/register\.html$"))


@pytest.mark.ui
def test_UI_03_navbar_login_link_opens_login(ui):
    ui.goto("/index.html")
    ui.page.click(".nav-links a[href='login.html']")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


@pytest.mark.ui
@pytest.mark.parametrize("path,title", [
    ("/index.html", "SecureBank - Simple, Secure Banking"),
    ("/login.html", "Login - SecureBank"),
    ("/register.html", "Register - SecureBank"),
])
def test_UI_04_public_page_titles(ui, path, title):
    ui.goto(path)
    expect(ui.page).to_have_title(title)


@pytest.mark.ui
@pytest.mark.parametrize("path,title,email", [
    ("/dashboard.html", "Dashboard - SecureBank", "alice@example.com"),
    ("/profile.html", "Profile - SecureBank", "alice@example.com"),
    ("/account-details.html", "Account Details - SecureBank", "alice@example.com"),
    ("/admin.html", "Admin - SecureBank", "admin@example.com"),
])
def test_UI_05_logged_in_page_titles(ui, path, title, email):
    ui.login_as(email, path)
    expect(ui.page).to_have_title(title)


# ---------------------------------------------------------------- register
@pytest.mark.ui
def test_UI_06_registration_succeeds_and_redirects_to_login(ui, db):
    data = fill_register(ui)
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page.locator("#successMsg")).to_contain_text("Registration successful")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"), timeout=6000)
    assert one(db, "SELECT name, role FROM users WHERE email = %s", (data["email"],)) == \
           {"name": "Carol White", "role": "customer"}


@pytest.mark.ui
def test_UI_07_duplicate_email_shows_error_message(ui):
    fill_register(ui, email="alice@example.com")
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Email already registered")
    assert "/register.html" in ui.url


@pytest.mark.ui
def test_UI_08_empty_registration_form_is_blocked_by_the_browser(ui, db):
    ui.goto("/register.html")
    ui.page.click("#registerForm button[type=submit]")
    assert ui.valid("#registerForm") is False
    assert scalar(db, "SELECT COUNT(*) FROM users") == 3


@pytest.mark.ui
@pytest.mark.parametrize("email", ["plainaddress", "no-at.com", "a@", "@b.com"])
def test_UI_09_invalid_email_is_blocked_by_the_browser(ui, email):
    fill_register(ui, email=email)
    assert ui.valid("#registerForm") is False


@pytest.mark.ui
def test_UI_10_password_shorter_than_the_backend_minimum_is_blocked_in_the_browser(ui):
    """The server requires 8+ characters; the form must not let 6 or 7 through."""
    fill_register(ui, password="1234567")
    assert ui.valid("#registerForm") is False


@pytest.mark.ui
def test_UI_11_server_side_validation_error_is_displayed(ui):
    fill_register(ui, phone="abc")
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Phone must be 7 to 15 digits")


@pytest.mark.ui
def test_UI_12_newly_registered_user_can_log_in_through_the_form(ui):
    data = fill_register(ui)
    ui.page.click("#registerForm button[type=submit]")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"), timeout=6000)
    ui.login_via_form(data["email"], data["password"])
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Hi, Carol White")


@pytest.mark.ui
def test_UI_13_password_field_is_masked(ui):
    ui.goto("/register.html")
    assert ui.page.get_attribute("#password", "type") == "password"
    ui.goto("/login.html")
    assert ui.page.get_attribute("#password", "type") == "password"


# ------------------------------------------------------------------- login
@pytest.mark.ui
def test_UI_14_customer_login_opens_the_dashboard(ui):
    ui.login_via_form("alice@example.com", "password123")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Hi, Alice Johnson")


@pytest.mark.ui
def test_UI_15_admin_login_opens_the_admin_panel(ui):
    ui.login_via_form("admin@example.com", "password123")
    expect(ui.page).to_have_url(re.compile(r"/admin\.html$"))
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Admin: Admin User")


@pytest.mark.ui
def test_UI_16_wrong_password_shows_error_and_stores_no_token(ui):
    ui.login_via_form("alice@example.com", "wrong-password")
    expect(ui.page.locator("#errorMsg")).to_have_text("Invalid email or password")
    assert "/login.html" in ui.url and ui.local("token") is None


@pytest.mark.ui
def test_UI_17_unknown_email_shows_the_same_error(ui):
    ui.login_via_form("nobody@example.com", "password123")
    expect(ui.page.locator("#errorMsg")).to_have_text("Invalid email or password")


@pytest.mark.ui
def test_UI_18_empty_login_form_is_blocked_by_the_browser(ui):
    ui.goto("/login.html")
    ui.page.click("#loginForm button[type=submit]")
    assert ui.valid("#loginForm") is False and "/login.html" in ui.url


@pytest.mark.ui
def test_UI_19_successful_login_stores_token_and_user_in_local_storage(ui):
    ui.login_via_form("alice@example.com", "password123")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))
    assert ui.local("token") and ui.local("token").count(".") == 2
    assert '"role":"customer"' in ui.local("user") and "password" not in ui.local("user")


@pytest.mark.ui
def test_UI_20_pressing_enter_submits_the_login_form(ui):
    ui.goto("/login.html")
    ui.page.fill("#email", "alice@example.com")
    ui.page.fill("#password", "password123")
    ui.page.press("#password", "Enter")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))


@pytest.mark.ui
def test_UI_21_sql_injection_text_in_the_password_field_does_not_log_in(ui):
    ui.login_via_form("alice@example.com", "' OR '1'='1")
    expect(ui.page.locator("#errorMsg")).to_have_text("Invalid email or password")
    assert ui.local("token") is None


@pytest.mark.ui
def test_UI_22_sql_injection_text_in_the_email_field_is_rejected_by_the_browser(ui):
    ui.goto("/login.html")
    ui.page.fill("#email", "' OR 1=1 --")
    ui.page.fill("#password", "x")
    assert ui.valid("#loginForm") is False


@pytest.mark.ui
def test_UI_23_login_page_links_to_registration(ui):
    ui.goto("/login.html")
    ui.page.click(".link-row a")
    expect(ui.page).to_have_url(re.compile(r"/register\.html$"))


# ------------------------------------------------------------ route guards
@pytest.mark.ui
@pytest.mark.parametrize("path", ["/dashboard.html", "/profile.html", "/account-details.html", "/admin.html"])
def test_UI_24_protected_pages_redirect_anonymous_visitors_to_login(ui, path):
    ui.goto(path)
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


@pytest.mark.ui
def test_UI_25_customer_opening_the_admin_page_is_sent_to_the_dashboard(ui):
    ui.login_as("alice@example.com", "/admin.html")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))


@pytest.mark.ui
def test_UI_26_logout_clears_the_session_and_returns_to_login(ui):
    ui.login_as("alice@example.com")
    ui.page.click("#logoutBtn")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))
    assert ui.local("token") is None and ui.local("user") is None
    ui.goto("/dashboard.html")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


@pytest.mark.ui
def test_UI_27_invalid_token_sends_the_user_back_to_login(ui):
    """A stale or tampered token must not leave the user on a broken page."""
    ui.set_storage("not.a.valid-token", {"user_id": 1, "name": "Alice Johnson", "role": "customer"})
    ui.goto("/dashboard.html")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


@pytest.mark.ui
def test_UI_28_editing_the_role_in_local_storage_does_not_unlock_admin_data(ui):
    """Client-side guards are cosmetic; the API must refuse the data."""
    data = ui.login_as("alice@example.com", "/dashboard.html")
    user = {**data["user"], "role": "admin"}
    ui.page.evaluate("u => localStorage.setItem('user', JSON.stringify(u))", user)
    ui.goto("/admin.html")
    ui.page.wait_for_timeout(1200)
    assert "/admin.html" in ui.url                       # the page shell opens...
    expect(ui.page.locator("#statUsers")).to_have_text("—")   # ...but no data arrives
    expect(ui.page.locator("#usersBody tr")).to_have_count(0)


# ------------------------------------------------------- general UI quality
@pytest.mark.ui
@pytest.mark.parametrize("path", ["/index.html", "/login.html", "/register.html"])
def test_UI_29_public_pages_load_without_errors_or_missing_files(ui, path):
    ui.goto(path)
    ui.page.wait_for_load_state("networkidle")
    assert ui.console_errors == [] and ui.bad_responses == []


@pytest.mark.ui
@pytest.mark.parametrize("path,email", [("/dashboard.html", "alice@example.com"),
                                        ("/profile.html", "alice@example.com"),
                                        ("/admin.html", "admin@example.com")])
def test_UI_30_logged_in_pages_load_without_errors_or_missing_files(ui, path, email):
    ui.login_as(email, path)
    ui.page.wait_for_load_state("networkidle")
    assert ui.console_errors == [] and ui.bad_responses == []


@pytest.mark.ui
def test_UI_31_stylesheet_is_applied(ui):
    ui.goto("/index.html")
    colour = ui.page.eval_on_selector(".navbar", "e => getComputedStyle(e).backgroundColor")
    assert colour != "rgba(0, 0, 0, 0)"


@pytest.mark.ui
@pytest.mark.parametrize("path", ["/index.html", "/login.html", "/register.html"])
def test_UI_32_public_pages_fit_a_phone_screen_without_sideways_scrolling(ui, path):
    ui.page.set_viewport_size({"width": 375, "height": 667})
    ui.goto(path)
    assert ui.has_horizontal_scroll() is False


@pytest.mark.ui
def test_UI_33_dashboard_fits_a_phone_screen_without_sideways_scrolling(ui):
    ui.page.set_viewport_size({"width": 375, "height": 667})
    ui.login_as("alice@example.com")
    expect(ui.page.locator(".account-card")).to_have_count(1)
    assert ui.has_horizontal_scroll() is False

# ============================================================================
# ui customer
# ============================================================================

MINUS = "−"      # the minus sign the statement page uses
RUPEE = "₹"


def submit(ui, form):
    ui.page.click(f"#{form}Form button[type=submit]")


def tab(ui, name):
    ui.page.click(f".tab-btn[data-tab={name}]")


def card_balance(ui, index=0):
    return ui.page.locator(".account-card .balance").nth(index)


# ---------------------------------------------------------------- accounts
@pytest.mark.ui
def test_UI_34_dashboard_lists_my_account_with_balance_status_and_branch(ui):
    ui.login_as("alice@example.com")
    card = ui.page.locator(".account-card")
    expect(card).to_have_count(1)
    expect(card).to_contain_text("Account #1")
    expect(card).to_contain_text("SAVINGS")
    expect(card).to_contain_text("Main Street Branch")
    expect(card.locator(".badge")).to_have_text("active")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}5000.00")


@pytest.mark.ui
def test_UI_35_dashboard_shows_only_the_logged_in_users_accounts(ui):
    ui.login_as("bob@example.com")
    expect(ui.page.locator(".account-card")).to_have_count(1)
    expect(ui.page.locator(".account-card")).to_contain_text("Account #2")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}3000.00")


@pytest.mark.ui
def test_UI_36_user_without_accounts_sees_a_friendly_message(ui, api):
    api.post("/api/auth/register", json={"name": "New Person", "email": "new@example.com", "password": "Passw0rd!"})
    ui.login_as("new@example.com", password="Passw0rd!")
    expect(ui.page.locator("#accountsList")).to_contain_text("No accounts yet")


@pytest.mark.ui
def test_UI_37_account_dropdowns_are_filled_with_my_accounts(ui):
    ui.login_as("alice@example.com")
    for select in ("#depositAccount", "#withdrawAccount", "#transferFrom"):
        expect(ui.page.locator(f"{select} option")).to_have_count(1)
        expect(ui.page.locator(f"{select} option")).to_contain_text(f"Account #1 (savings) - {RUPEE}5000.00")


@pytest.mark.ui
def test_UI_38_branch_dropdown_lists_all_branches_with_ifsc(ui):
    ui.login_as("alice@example.com")
    options = ui.page.locator("#branchSelect option")
    expect(options).to_have_count(3)
    texts = options.all_inner_texts()
    assert "Main Street Branch (BANK0001234)" in texts and all("BANK000" in t for t in texts)


@pytest.mark.ui
def test_UI_39_open_new_account_form_toggles(ui):
    ui.login_as("alice@example.com")
    expect(ui.page.locator("#newAccountSection")).to_be_hidden()
    ui.page.click("#newAccountBtn")
    expect(ui.page.locator("#newAccountSection")).to_be_visible()
    ui.page.click("#newAccountBtn")
    expect(ui.page.locator("#newAccountSection")).to_be_hidden()


@pytest.mark.ui
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
@pytest.mark.ui
def test_UI_41_deposit_updates_the_balance_on_screen_and_in_the_database(ui, db):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", "250.50")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnSuccess")).to_have_text("Deposit successful!")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}5250.50")
    assert balance(db, 1) == Decimal("5250.50")
    expect(ui.page.locator("#depositAmount")).to_have_value("")      # form reset


@pytest.mark.ui
def test_UI_42_withdrawal_updates_the_balance(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "withdraw")
    ui.page.fill("#withdrawAmount", "1000")
    submit(ui, "withdraw")
    expect(ui.page.locator("#txnSuccess")).to_have_text("Withdrawal successful!")
    expect(card_balance(ui)).to_have_text(f"{RUPEE}4000.00")
    assert balance(db, 1) == 4000


@pytest.mark.ui
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


@pytest.mark.ui
def test_UI_44_withdrawing_more_than_the_balance_shows_the_server_error(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "withdraw")
    ui.page.fill("#withdrawAmount", "99999")
    submit(ui, "withdraw")
    expect(ui.page.locator("#txnError")).to_have_text("Insufficient balance")
    assert balance(db, 1) == 5000


@pytest.mark.ui
def test_UI_45_transfer_to_the_same_account_is_refused_on_screen(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "transfer")
    ui.page.fill("#transferTo", "1")
    ui.page.fill("#transferAmount", "10")
    submit(ui, "transfer")
    expect(ui.page.locator("#txnError")).to_have_text("Cannot transfer to the same account.")
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 0


@pytest.mark.ui
def test_UI_46_transfer_to_a_nonexistent_account_shows_the_server_error(ui, db):
    ui.login_as("alice@example.com")
    tab(ui, "transfer")
    ui.page.fill("#transferTo", "99999")
    ui.page.fill("#transferAmount", "10")
    submit(ui, "transfer")
    expect(ui.page.locator("#txnError")).to_have_text("Destination account not found")
    assert balance(db, 1) == 5000


@pytest.mark.ui
@pytest.mark.parametrize("amount", ["0", "-5", "10.999", "0.001"])
def test_UI_47_invalid_deposit_amounts_are_blocked_by_the_browser(ui, db, amount):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", amount)
    submit(ui, "deposit")
    assert ui.valid("#depositForm") is False
    expect(ui.page.locator("#txnSuccess")).to_be_hidden()
    assert balance(db, 1) == 5000


@pytest.mark.ui
def test_UI_48_empty_amount_is_blocked_by_the_browser(ui):
    ui.login_as("alice@example.com")
    submit(ui, "deposit")
    assert ui.valid("#depositForm") is False


@pytest.mark.ui
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


@pytest.mark.ui
def test_UI_50_switching_tab_clears_the_previous_message(ui):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", "10")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnSuccess")).to_be_visible()
    tab(ui, "withdraw")
    expect(ui.page.locator("#txnSuccess")).to_be_hidden()


@pytest.mark.ui
def test_UI_51_frozen_account_cannot_receive_a_deposit(ui, db):
    run(db, "UPDATE accounts SET status = 'frozen' WHERE account_id = 1")
    ui.login_as("alice@example.com")
    expect(ui.page.locator(".account-card .badge")).to_have_text("frozen")
    ui.page.fill("#depositAmount", "10")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnError")).to_have_text("Account is not active")
    assert balance(db, 1) == 5000


@pytest.mark.ui
def test_UI_52_overflowing_deposit_shows_a_clear_error(ui, db):
    ui.login_as("alice@example.com")
    ui.page.fill("#depositAmount", "9999999999999.99")
    submit(ui, "deposit")
    expect(ui.page.locator("#txnError")).to_contain_text("maximum")
    assert balance(db, 1) == 5000


# --------------------------------------------------------------- statement
@pytest.mark.ui
def test_UI_53_view_statement_link_opens_the_account_details_page(ui):
    ui.login_as("alice@example.com")
    ui.page.click(".view-statement-link")
    expect(ui.page).to_have_url(re.compile(r"/account-details\.html$"))
    expect(ui.page.locator("#accountTitle")).to_have_text("Account #1")


@pytest.mark.ui
def test_UI_54_account_details_shows_summary_and_balance(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
    ui.goto("/account-details.html")
    expect(ui.page.locator("#accountMeta")).to_have_text("SAVINGS — Main Street Branch (BANK0001234)")
    expect(ui.page.locator("#accountStatusBadge")).to_have_text("active")
    expect(ui.page.locator("#accountBalance")).to_have_text(f"{RUPEE}5000.00")


@pytest.mark.ui
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


@pytest.mark.ui
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


@pytest.mark.ui
def test_UI_57_account_without_activity_shows_no_transactions_message(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
    ui.goto("/account-details.html")
    expect(ui.page.locator("#statementBody")).to_contain_text("No transactions yet.")
    expect(ui.page.locator("#txnCount")).to_have_text("0")


@pytest.mark.ui
def test_UI_58_account_details_without_a_selected_account_shows_not_found(ui):
    ui.login_as("alice@example.com", "/account-details.html")
    expect(ui.page.locator("#notFoundBox")).to_be_visible()
    expect(ui.page.locator("#accountContent")).to_be_hidden()


@pytest.mark.ui
def test_UI_59_someone_elses_account_id_in_session_storage_shows_not_found(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '2')")
    ui.goto("/account-details.html")
    expect(ui.page.locator("#notFoundBox")).to_be_visible()
    expect(ui.page.locator("#accountBalance")).not_to_contain_text("3000")


@pytest.mark.ui
def test_UI_60_back_link_returns_to_the_dashboard(ui):
    ui.login_as("alice@example.com")
    ui.page.evaluate("sessionStorage.setItem('viewAccountId', '1')")
    ui.goto("/account-details.html")
    ui.page.click("text=Back to Dashboard")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))


# ----------------------------------------------------------------- profile
@pytest.mark.ui
def test_UI_61_profile_form_is_prefilled_and_read_only_fields_are_disabled(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    expect(ui.page.locator("#email")).to_have_value("alice@example.com")
    expect(ui.page.locator("#phone")).to_have_value("9876543210")
    expect(ui.page.locator("#role")).to_have_value("customer")
    for field in ("#email", "#role", "#createdAt"):
        expect(ui.page.locator(field)).to_be_disabled()
    assert ui.page.input_value("#createdAt") != ""


@pytest.mark.ui
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


@pytest.mark.ui
def test_UI_63_invalid_phone_on_profile_shows_the_server_error(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    ui.page.fill("#phone", "abc")
    ui.page.click("#profileForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Phone must be 7 to 15 digits")


@pytest.mark.ui
def test_UI_64_empty_name_on_profile_is_blocked_by_the_browser(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    ui.page.fill("#name", "")
    ui.page.click("#profileForm button[type=submit]")
    assert ui.valid("#profileForm") is False


@pytest.mark.ui
def test_UI_65_overlong_name_on_profile_shows_the_server_error(ui):
    ui.login_as("alice@example.com", "/profile.html")
    expect(ui.page.locator("#name")).to_have_value("Alice Johnson")
    ui.page.fill("#name", "N" * 101)
    ui.page.click("#profileForm button[type=submit]")
    expect(ui.page.locator("#errorMsg")).to_have_text("Name must be at most 100 characters")


@pytest.mark.ui
def test_UI_66_navbar_links_move_between_dashboard_and_profile(ui):
    ui.login_as("alice@example.com")
    ui.page.click(".nav-links a[href='profile.html']")
    expect(ui.page).to_have_url(re.compile(r"/profile\.html$"))
    ui.page.click(".nav-links a[href='dashboard.html']")
    expect(ui.page).to_have_url(re.compile(r"/dashboard\.html$"))

# ============================================================================
# ui admin
# ============================================================================

XSS_IMG = '<img src=x onerror="window.__xss=1">'


def admin_tab(ui, name):
    ui.page.click(f".admin-tab-btn[data-tab={name}]")


# ------------------------------------------------------------------- admin
@pytest.mark.ui
def test_UI_67_overview_cards_show_the_right_totals(ui):
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#statUsers")).to_have_text("3")
    expect(ui.page.locator("#statAccounts")).to_have_text("2")
    expect(ui.page.locator("#statTxns")).to_have_text("0")
    expect(ui.page.locator("#statBalance")).to_have_text(f"{RUPEE}8000.00")


@pytest.mark.ui
def test_UI_68_users_tab_lists_every_user_without_password_data(ui):
    ui.login_as("admin@example.com")
    body = ui.page.locator("#usersBody")
    expect(body.locator("tr")).to_have_count(3)
    for text in ("Alice Johnson", "bob@example.com", "admin"):
        expect(body).to_contain_text(text)
    assert "$2b$" not in ui.page.content()


@pytest.mark.ui
def test_UI_69_admin_tabs_show_one_panel_at_a_time(ui):
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#usersPanel")).to_be_visible()
    for name in ("accounts", "transactions", "auditlog"):
        admin_tab(ui, name)
        expect(ui.page.locator(f"#{name}Panel")).to_be_visible()
        expect(ui.page.locator(".admin-panel:visible")).to_have_count(1)
    expect(ui.page.locator("#usersPanel")).to_be_hidden()


@pytest.mark.ui
def test_UI_70_accounts_tab_shows_owner_balance_status_and_actions(ui):
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    first = ui.page.locator("#accountsBody tr").nth(0)
    expect(first).to_contain_text("Alice Johnson (alice@example.com)")
    expect(first).to_contain_text(f"{RUPEE}5000.00")
    expect(first.locator(".badge")).to_have_text("active")
    expect(first.locator("button")).to_have_text(["Freeze", "Close"])     # no "Activate" while active


@pytest.mark.ui
def test_UI_71_freezing_an_account_updates_the_page_and_blocks_the_customer(ui, db, api):
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='frozen']")
    first = ui.page.locator("#accountsBody tr").nth(0)
    expect(first.locator(".badge")).to_have_text("frozen")
    expect(first.locator("button")).to_have_text(["Activate", "Close"])
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "frozen"
    assert api.deposit(api.login("alice@example.com"), 1, 10).status_code == 400


@pytest.mark.ui
def test_UI_72_activating_a_frozen_account_restores_it(ui, db):
    run(db, "UPDATE accounts SET status = 'frozen' WHERE account_id = 1")
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='active']")
    expect(ui.page.locator("#accountsBody tr").nth(0).locator(".badge")).to_have_text("active")
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


@pytest.mark.ui
def test_UI_73_closing_an_account_that_still_has_money_shows_an_alert(ui, db):
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='closed']")
    assert ui.wait_dialog() == "Account must have zero balance before it can be closed"
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "active"


@pytest.mark.ui
def test_UI_74_closing_an_empty_account_works_and_removes_its_action_buttons(ui, db):
    run(db, "UPDATE accounts SET balance = 0 WHERE account_id = 1")
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='closed']")
    first = ui.page.locator("#accountsBody tr").nth(0)
    expect(first.locator(".badge")).to_have_text("closed")
    expect(first.locator("button")).to_have_text(["Activate", "Freeze"])


@pytest.mark.ui
def test_UI_75_reopening_a_closed_account_is_refused_with_an_alert(ui, db):
    run(db, "UPDATE accounts SET balance = 0, status = 'closed' WHERE account_id = 1")
    ui.login_as("admin@example.com")
    admin_tab(ui, "accounts")
    ui.page.click(".status-btn[data-id='1'][data-status='active']")
    assert ui.wait_dialog() == "A closed account cannot be changed"
    assert scalar(db, "SELECT status FROM accounts WHERE account_id = 1") == "closed"


@pytest.mark.ui
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


@pytest.mark.ui
def test_UI_77_audit_log_tab_shows_balance_changes_with_owner(ui, api):
    api.deposit(api.login("alice@example.com"), 1, 100)
    ui.login_as("admin@example.com")
    admin_tab(ui, "auditlog")
    row = ui.page.locator("#auditBody tr")
    expect(row).to_have_count(1)
    for text in ("Alice Johnson", "BALANCE_UPDATE", f"{RUPEE}5000.00", f"{RUPEE}5100.00"):
        expect(row).to_contain_text(text)


@pytest.mark.ui
def test_UI_78_overview_total_balance_updates_after_a_customer_deposit(ui, api):
    api.deposit(api.login("bob@example.com"), 2, 500)
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#statBalance")).to_have_text(f"{RUPEE}8500.00")


@pytest.mark.ui
def test_UI_79_admin_logout_returns_to_login(ui):
    ui.login_as("admin@example.com")
    ui.page.click("#logoutBtn")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))
    ui.goto("/admin.html")
    expect(ui.page).to_have_url(re.compile(r"/login\.html$"))


# ----------------------------------------------------------- XSS (security)
@pytest.mark.ui
def test_UI_80_script_in_a_users_name_does_not_run_in_the_admin_panel(ui, api):
    """Stored XSS: a customer registers with HTML in their name; the admin opens the Users tab.
    The text must be shown literally, never executed."""
    api.post("/api/auth/register", json={"name": XSS_IMG, "email": "xss@example.com", "password": "Passw0rd!"})
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#usersBody tr")).to_have_count(4)
    ui.page.wait_for_timeout(600)
    assert ui.page.evaluate("window.__xss") is None, "script from a user's name ran in the admin's browser"
    expect(ui.page.locator("#usersBody")).to_contain_text("<img src=x")      # shown as plain text


@pytest.mark.ui
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


@pytest.mark.ui
def test_UI_82_script_in_an_email_cannot_run_in_the_admin_panel(ui, db):
    """Same check for the email column (inserted directly, since the API validates email format)."""
    run(db, "UPDATE users SET email = %s WHERE user_id = 2", ('"><img src=x onerror="window.__xss=1">',))
    ui.login_as("admin@example.com")
    expect(ui.page.locator("#usersBody tr")).to_have_count(3)
    ui.page.wait_for_timeout(600)
    assert ui.page.evaluate("window.__xss") is None


@pytest.mark.ui
def test_UI_83_welcome_message_shows_html_in_a_name_as_plain_text(ui, api):
    api.post("/api/auth/register", json={"name": "<b>Bold</b>", "email": "b@example.com", "password": "Passw0rd!"})
    ui.login_as("b@example.com", password="Passw0rd!")
    expect(ui.page.locator("#welcomeMsg")).to_have_text("Hi, <b>Bold</b>")
    assert ui.page.locator("#welcomeMsg b").count() == 0
