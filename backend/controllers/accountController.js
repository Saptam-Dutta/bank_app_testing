const pool = require('../config/db');
const { parseId } = require('../utils/validators');

// ==========================
// GET MY ACCOUNTS (all accounts belonging to logged-in user)
// ==========================
exports.getMyAccounts = async (req, res) => {
  try {
    const [rows] = await pool.query(
      `SELECT a.account_id, a.account_type, a.balance, a.status, a.created_at,
              b.branch_name, b.ifsc_code
       FROM accounts a
       JOIN branches b ON a.branch_id = b.branch_id
       WHERE a.user_id = ?
       ORDER BY a.account_id`,
      [req.user.user_id]
    );

    res.json(rows);
  } catch (err) {
    console.error('GetMyAccounts error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// GET SINGLE ACCOUNT (must belong to logged-in user)
// ==========================
exports.getAccountById = async (req, res) => {
  const id = parseId(req.params.id);
  if (!id) {
    return res.status(400).json({ error: 'Invalid account id' });
  }

  try {
    const [rows] = await pool.query(
      `SELECT a.account_id, a.account_type, a.balance, a.status, a.created_at,
              b.branch_name, b.ifsc_code
       FROM accounts a
       JOIN branches b ON a.branch_id = b.branch_id
       WHERE a.account_id = ? AND a.user_id = ?`,
      [id, req.user.user_id]
    );

    if (rows.length === 0) {
      return res.status(404).json({ error: 'Account not found' });
    }

    res.json(rows[0]);
  } catch (err) {
    console.error('GetAccountById error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// GET ACCOUNT STATEMENT (history + running summary) - promised in the synopsis
// ==========================
exports.getStatement = async (req, res) => {
  const id = parseId(req.params.id);
  if (!id) {
    return res.status(400).json({ error: 'Invalid account id' });
  }

  try {
    const [acct] = await pool.query(
      'SELECT account_id, balance, status FROM accounts WHERE account_id = ? AND user_id = ?',
      [id, req.user.user_id]
    );
    if (acct.length === 0) {
      return res.status(404).json({ error: 'Account not found' });
    }

    const [txns] = await pool.query(
      `SELECT transaction_id, from_account_id, to_account_id, amount, type, status, description, created_at
       FROM transactions
       WHERE (from_account_id = ? OR to_account_id = ?) AND status = 'success'
       ORDER BY created_at DESC, transaction_id DESC`,
      [id, id]
    );

    let totalIn = 0;
    let totalOut = 0;
    const entries = txns.map(t => {
      const credit = t.to_account_id === id;
      const cents = Math.round(Number(t.amount) * 100);
      if (credit) totalIn += cents; else totalOut += cents;
      return { ...t, direction: credit ? 'credit' : 'debit' };
    });

    res.json({
      account_id: id,
      current_balance: acct[0].balance,
      status: acct[0].status,
      summary: {
        total_credits: (totalIn / 100).toFixed(2),
        total_debits: (totalOut / 100).toFixed(2),
        transaction_count: entries.length
      },
      transactions: entries
    });
  } catch (err) {
    console.error('GetStatement error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// CREATE NEW ACCOUNT (for logged-in user)
// ==========================
exports.createAccount = async (req, res) => {
  const body = req.body || {};
  const branch_id = parseId(body.branch_id);
  const { account_type } = body;

  if (!branch_id || !account_type) {
    return res.status(400).json({ error: 'branch_id and account_type are required' });
  }

  if (!['savings', 'current'].includes(account_type)) {
    return res.status(400).json({ error: 'account_type must be savings or current' });
  }

  try {
    const [branch] = await pool.query('SELECT branch_id FROM branches WHERE branch_id = ?', [branch_id]);
    if (branch.length === 0) {
      return res.status(404).json({ error: 'Branch not found' });
    }

    const [result] = await pool.query(
      'INSERT INTO accounts (user_id, branch_id, account_type, balance, status) VALUES (?, ?, ?, 0.00, ?)',
      [req.user.user_id, branch_id, account_type, 'active']
    );

    res.status(201).json({
      message: 'Account created successfully',
      account_id: result.insertId
    });
  } catch (err) {
    console.error('CreateAccount error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};
