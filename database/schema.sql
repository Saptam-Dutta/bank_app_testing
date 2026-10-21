USE bank_app;

-- ==========================
-- BRANCHES
-- ==========================
CREATE TABLE branches (
    branch_id INT AUTO_INCREMENT PRIMARY KEY,
    branch_name VARCHAR(100) NOT NULL,
    ifsc_code VARCHAR(20) UNIQUE NOT NULL,
    address VARCHAR(255)
);

-- ==========================
-- USERS
-- ==========================
CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(15),
    role ENUM('customer', 'admin') DEFAULT 'customer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================
-- ACCOUNTS
-- ==========================
CREATE TABLE accounts (
    account_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    branch_id INT NOT NULL,
    account_type ENUM('savings', 'current') DEFAULT 'savings',
    balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
    status ENUM('active', 'frozen', 'closed') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_account_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_account_branch FOREIGN KEY (branch_id) REFERENCES branches(branch_id),
    CONSTRAINT chk_balance_nonnegative CHECK (balance >= 0)
);

-- ==========================
-- TRANSACTIONS
-- ==========================
CREATE TABLE transactions (
    transaction_id INT AUTO_INCREMENT PRIMARY KEY,
    from_account_id INT NULL,
    to_account_id INT NULL,
    amount DECIMAL(15,2) NOT NULL,
    type ENUM('deposit', 'withdrawal', 'transfer') NOT NULL,
    status ENUM('pending', 'success', 'failed') DEFAULT 'pending',
    description VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_txn_from FOREIGN KEY (from_account_id) REFERENCES accounts(account_id),
    CONSTRAINT fk_txn_to FOREIGN KEY (to_account_id) REFERENCES accounts(account_id),
    CONSTRAINT chk_amount_positive CHECK (amount > 0)
);

-- ==========================
-- LOANS
-- ==========================
CREATE TABLE loans (
    loan_id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    interest_rate DECIMAL(5,2) NOT NULL,
    tenure_months INT NOT NULL,
    status ENUM('pending', 'approved', 'rejected', 'closed') DEFAULT 'pending',
    issued_date DATE NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_loan_account FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

-- ==========================
-- AUDIT LOG (populated via triggers)
-- ==========================
CREATE TABLE audit_log (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NOT NULL,
    action VARCHAR(50),
    old_balance DECIMAL(15,2),
    new_balance DECIMAL(15,2),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_account FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

-- ==========================
-- INDEXES (for performance testing later)
-- ==========================
CREATE INDEX idx_txn_from ON transactions(from_account_id);
CREATE INDEX idx_txn_to ON transactions(to_account_id);
CREATE INDEX idx_txn_created ON transactions(created_at);
CREATE INDEX idx_accounts_user ON accounts(user_id);

-- ==========================
-- TRIGGER: log every balance update
-- ==========================
DELIMITER $$

CREATE TRIGGER trg_account_balance_update
AFTER UPDATE ON accounts
FOR EACH ROW
BEGIN
    IF OLD.balance <> NEW.balance THEN
        INSERT INTO audit_log (account_id, action, old_balance, new_balance)
        VALUES (NEW.account_id, 'BALANCE_UPDATE', OLD.balance, NEW.balance);
    END IF;
END$$

DELIMITER ;