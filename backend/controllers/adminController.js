const pool = require('../config/db');
const { parseId } = require('../utils/validators');

// ==========================
// GET ALL USERS
// ==========================
exports.getAllUsers = async (req, res) => {
  try {
    const [rows] = await pool.query(
      'SELECT user_id, name, email, phone, role, created_at FROM users ORDER BY user_id'
    );
    res.json(rows);
  } catch (err) {
    console.error('GetAllUsers error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// GET ALL ACCOUNTS (with owner info)
// ==========================
exports.getAllAccounts = async (req, res) => {
  try {
    const [rows] = await pool.query(
      `SELECT a.account_id, a.account_type, a.balance, a.status, a.created_at,
              u.user_id, u.name AS owner_name, u.email AS owner_email,
              b.branch_name
       FROM accounts a
       JOIN users u ON a.user_id = u.user_id
       JOIN branches b ON a.branch_id = b.branch_id
       ORDER BY a.account_id`
    );
    res.json(rows);
  } catch (err) {
    console.error('GetAllAccounts error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// UPDATE ACCOUNT STATUS (freeze / unfreeze / close)
// Rules: a closed account is final; an account must be empty before it can be closed.
// ==========================
exports.updateAccountStatus = async (req, res) => {
  const id = parseId(req.params.id);
  const { status } = req.body || {};

  if (!id) {
    return res.status(400).json({ error: 'Invalid account id' });
  }
  if (!['active', 'frozen', 'closed'].includes(status)) {
    return res.status(400).json({ error: 'Invalid status. Must be active, frozen, or closed' });
  }

  const connection = await pool.getConnection();
  try {
    await connection.beginTransaction();

    const [existing] = await connection.query(
      'SELECT account_id, status, balance FROM accounts WHERE account_id = ? FOR UPDATE',
      [id]
    );
    if (existing.length === 0) {
      await connection.rollback();
      return res.status(404).json({ error: 'Account not found' });
    }

    const acct = existing[0];
    if (acct.status === 'closed') {
      await connection.rollback();
      return res.status(400).json({ error: 'A closed account cannot be changed' });
    }
    if (status === 'closed' && Math.round(Number(acct.balance) * 100) !== 0) {
      await connection.rollback();
      return res.status(400).json({ error: 'Account must have zero balance before it can be closed' });
    }

    await connection.query('UPDATE accounts SET status = ? WHERE account_id = ?', [status, id]);
    await connection.commit();

    res.json({ message: `Account status updated to ${status}` });
  } catch (err) {
    await connection.rollback();
    console.error('UpdateAccountStatus error:', err.message);
    res.status(500).json({ error: 'Server error' });
  } finally {
    connection.release();
  }
};

// ==========================
// GET ALL TRANSACTIONS (system-wide)
// ==========================
exports.getAllTransactions = async (req, res) => {
  try {
    const [rows] = await pool.query(
      `SELECT transaction_id, from_account_id, to_account_id, amount, type, status, description, created_at
       FROM transactions
       ORDER BY created_at DESC, transaction_id DESC
       LIMIT 200`
    );
    res.json(rows);
  } catch (err) {
    console.error('GetAllTransactions error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// GET AUDIT LOG
// ==========================
exports.getAuditLog = async (req, res) => {
  try {
    const [rows] = await pool.query(
      `SELECT al.log_id, al.account_id, al.action, al.old_balance, al.new_balance, al.changed_at,
              u.name AS owner_name
       FROM audit_log al
       JOIN accounts a ON al.account_id = a.account_id
       JOIN users u ON a.user_id = u.user_id
       ORDER BY al.changed_at DESC, al.log_id DESC
       LIMIT 200`
    );
    res.json(rows);
  } catch (err) {
    console.error('GetAuditLog error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// DASHBOARD STATS
// ==========================
exports.getStats = async (req, res) => {
  try {
    const [[userCount]] = await pool.query('SELECT COUNT(*) AS count FROM users');
    const [[accountCount]] = await pool.query('SELECT COUNT(*) AS count FROM accounts');
    const [[txnCount]] = await pool.query('SELECT COUNT(*) AS count FROM transactions');
    const [[totalBalance]] = await pool.query('SELECT SUM(balance) AS total FROM accounts');

    res.json({
      totalUsers: userCount.count,
      totalAccounts: accountCount.count,
      totalTransactions: txnCount.count,
      totalBalance: totalBalance.total || 0
    });
  } catch (err) {
    console.error('GetStats error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};
