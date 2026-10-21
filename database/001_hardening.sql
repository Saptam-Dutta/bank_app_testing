USE bank_app;

-- ======================================================================
-- Migration 001: database-level hardening (run once on the existing bank_app)
-- Each statement is independent; if one fails because it was already applied,
-- continue with the next one.
-- ======================================================================

-- 1. Loans: reject nonsense values
ALTER TABLE loans ADD CONSTRAINT chk_loan_amount_positive CHECK (amount > 0);
ALTER TABLE loans ADD CONSTRAINT chk_loan_rate_nonneg CHECK (interest_rate >= 0);
ALTER TABLE loans ADD CONSTRAINT chk_loan_tenure_positive CHECK (tenure_months > 0);

-- 2. Transactions: the type must agree with which account columns are filled,
--    and a transfer can never go from an account to itself
ALTER TABLE transactions ADD CONSTRAINT chk_txn_shape CHECK (
    (type = 'deposit'    AND from_account_id IS NULL     AND to_account_id IS NOT NULL)
 OR (type = 'withdrawal' AND from_account_id IS NOT NULL AND to_account_id IS NULL)
 OR (type = 'transfer'   AND from_account_id IS NOT NULL AND to_account_id IS NOT NULL
                         AND from_account_id <> to_account_id)
);

-- 3. Audit log must survive account/user deletion (it was ON DELETE CASCADE)
ALTER TABLE audit_log DROP FOREIGN KEY fk_audit_account;
ALTER TABLE audit_log ADD CONSTRAINT fk_audit_account
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE RESTRICT;

-- 4. Seed data hygiene: emails are stored lower-case by the API
UPDATE users SET email = LOWER(email) WHERE user_id > 0;
