USE bank_app;

-- ==========================
-- BRANCH
-- ==========================
INSERT INTO branches (branch_name, ifsc_code, address)
VALUES ('Main Street Branch', 'BANK0001234', '123 Main Street, City Center');
INSERT INTO branches (branch_name, ifsc_code, address)
VALUES ('Downtown Branch', 'BANK0002345', '45 Downtown Ave, City Center');
INSERT INTO branches (branch_name, ifsc_code, address)
VALUES ('Riverside Branch', 'BANK0003456', '12 Riverside Road, Uptown');

-- ==========================
-- USERS
-- password for both = "password123"
-- (hash generated with bcrypt, 10 rounds — we'll verify login works in the API step)
-- ==========================
INSERT INTO users (name, email, password_hash, phone, role)
VALUES
('Alice Johnson', 'alice@example.com', '$2b$10$qPIYtRy.bTegvNXyDgy3BOeOy5TQo9idlgQDgwZZSclxoZAn8wFdu', '9876543210', 'customer'),
('Bob Smith', 'bob@example.com', '$2b$10$qPIYtRy.bTegvNXyDgy3BOeOy5TQo9idlgQDgwZZSclxoZAn8wFdu', '9876543211', 'customer'),
('Admin User', 'admin@example.com', '$2b$10$qPIYtRy.bTegvNXyDgy3BOeOy5TQo9idlgQDgwZZSclxoZAn8wFdu', '9999999999', 'admin');

-- ==========================user_id
-- ACCOUNTS
-- ==========================
INSERT INTO accounts (user_id, branch_id, account_type, balance, status)
VALUES
(1, 1, 'savings', 5000.00, 'active'),
(2, 1, 'savings', 3000.00, 'active');