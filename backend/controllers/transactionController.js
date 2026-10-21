const pool = require('../config/db');
const { parseId, parseAmount, toCents, MAX_BALANCE_CENTS } = require('../utils/validators');

// ==========================
// HELPER: verify account belongs to logged-in user (locks the row)
// ==========================
async function getOwnedAccount(connection, accountId, userId) {
  const [rows] = await connection.query(
    'SELECT * FROM accounts WHERE account_id = ? AND user_id = ? FOR UPDATE',
    [accountId, userId]
  );
  return rows[0] || null;
}

// ==========================
// DEPOSIT
// ==========================
exports.deposit = async (req, res) => {
  const body = req.body || {};
  const account_id = parseId(body.account_id);
  const amount = parseAmount(body.amount);

  if (!account_id || !amount) {
    return res.status(400).json({
      error: 'Valid account_id and positive amount (max 2 decimals) are required'
    });
  }

  const connection = await pool.getConnection();

  try {
    await connection.beginTransaction();

    const account = await getOwnedAccount(connection, account_id, req.user.user_id);
    if (!account) {
      await connection.rollback();
      return res.status(404).json({ error: 'Account not found' });
    }
    if (account.status !== 'active') {
      await connection.rollback();
      return res.status(400).json({ error: 'Account is not active' });
    }
    if (toCents(account.balance) + toCents(amount) > MAX_BALANCE_CENTS) {
      await connection.rollback();
      return res.status(400).json({ error: 'Deposit would exceed the maximum allowed balance' });
    }

    await connection.query(
      'UPDATE accounts SET balance = balance + ? WHERE account_id = ?',
      [amount, account_id]
    );

    const [txnResult] = await connection.query(
      `INSERT INTO transactions (from_account_id, to_account_id, amount, type, status, description)
       VALUES (NULL, ?, ?, 'deposit', 'success', 'Cash deposit')`,
      [account_id, amount]
    );

    await connection.commit();

    res.status(201).json({
      message: 'Deposit successful',
      transaction_id: txnResult.insertId
    });
  } catch (err) {
    await connection.rollback();
    console.error('Deposit error:', err.message);
    res.status(500).json({ error: 'Server error during deposit' });
  } finally {
    connection.release();
  }
};

// ==========================
// WITHDRAW
// ==========================
exports.withdraw = async (req, res) => {
  const body = req.body || {};
  const account_id = parseId(body.account_id);
  const amount = parseAmount(body.amount);

  if (!account_id || !amount) {
    return res.status(400).json({
      error: 'Valid account_id and positive amount (max 2 decimals) are required'
    });
  }

  const connection = await pool.getConnection();

  try {
    await connection.beginTransaction();

    const account = await getOwnedAccount(connection, account_id, req.user.user_id);
    if (!account) {
      await connection.rollback();
      return res.status(404).json({ error: 'Account not found' });
    }
    if (account.status !== 'active') {
      await connection.rollback();
      return res.status(400).json({ error: 'Account is not active' });
    }
    if (toCents(account.balance) < toCents(amount)) {
      await connection.rollback();
      return res.status(400).json({ error: 'Insufficient balance' });
    }

    await connection.query(
      'UPDATE accounts SET balance = balance - ? WHERE account_id = ?',
      [amount, account_id]
    );

    const [txnResult] = await connection.query(
      `INSERT INTO transactions (from_account_id, to_account_id, amount, type, status, description)
       VALUES (?, NULL, ?, 'withdrawal', 'success', 'Cash withdrawal')`,
      [account_id, amount]
    );

    await connection.commit();

    res.status(201).json({
      message: 'Withdrawal successful',
      transaction_id: txnResult.insertId
    });
  } catch (err) {
    await connection.rollback();
    console.error('Withdraw error:', err.message);
    res.status(500).json({ error: 'Server error during withdrawal' });
  } finally {
    connection.release();
  }
};

// ==========================
// TRANSFER (atomic, locked, two-account update)
// ==========================
exports.transfer = async (req, res) => {
  const body = req.body || {};
  const from_account_id = parseId(body.from_account_id);
  const to_account_id = parseId(body.to_account_id);
  const amount = parseAmount(body.amount);
  let description = body.description;

  if (!from_account_id || !to_account_id || !amount) {
    return res.status(400).json({
      error: 'from_account_id, to_account_id, and positive amount (max 2 decimals) are required'
    });
  }

  // ids are normalised to numbers first, so "1" vs 1 can no longer bypass this check
  if (from_account_id === to_account_id) {
    return res.status(400).json({ error: 'Cannot transfer to the same account' });
  }

  if (description !== undefined && description !== null) {
    if (typeof description !== 'string' || description.length > 255) {
      return res.status(400).json({ error: 'description must be a string of at most 255 characters' });
    }
  }
  description = description || 'Fund transfer';

  const connection = await pool.getConnection();

  try {
    await connection.beginTransaction();

    // Lock both rows in one statement, ordered by account_id (lowest first), so two
    // opposite-direction transfers always acquire locks in the same order: no deadlock.
    const [locked] = await connection.query(
      'SELECT * FROM accounts WHERE account_id IN (?, ?) ORDER BY account_id FOR UPDATE',
      [from_account_id, to_account_id]
    );

    const sender = locked.find(a => a.account_id === from_account_id);
    const receiver = locked.find(a => a.account_id === to_account_id);

    if (!sender || sender.user_id !== req.user.user_id) {
      await connection.rollback();
      return res.status(404).json({ error: 'Source account not found or not owned by you' });
    }
    if (sender.status !== 'active') {
      await connection.rollback();
      return res.status(400).json({ error: 'Source account is not active' });
    }
    if (!receiver) {
      await connection.rollback();
      return res.status(404).json({ error: 'Destination account not found' });
    }
    if (receiver.status !== 'active') {
      await connection.rollback();
      return res.status(400).json({ error: 'Destination account is not active' });
    }
    if (toCents(sender.balance) < toCents(amount)) {
      await connection.rollback();
      return res.status(400).json({ error: 'Insufficient balance' });
    }
    if (toCents(receiver.balance) + toCents(amount) > MAX_BALANCE_CENTS) {
      await connection.rollback();
      return res.status(400).json({ error: 'Transfer would exceed the destination account\'s maximum balance' });
    }

    await connection.query(
      'UPDATE accounts SET balance = balance - ? WHERE account_id = ?',
      [amount, from_account_id]
    );
    await connection.query(
      'UPDATE accounts SET balance = balance + ? WHERE account_id = ?',
      [amount, to_account_id]
    );

    const [txnResult] = await connection.query(
      `INSERT INTO transactions (from_account_id, to_account_id, amount, type, status, description)
       VALUES (?, ?, ?, 'transfer', 'success', ?)`,
      [from_account_id, to_account_id, amount, description]
    );

    await connection.commit();

    res.status(201).json({
      message: 'Transfer successful',
      transaction_id: txnResult.insertId
    });
  } catch (err) {
    await connection.rollback();
    console.error('Transfer error:', err.message);
    res.status(500).json({ error: 'Server error during transfer' });
  } finally {
    connection.release();
  }
};

// ==========================
// GET MY TRANSACTION HISTORY
// ==========================
exports.getMyTransactions = async (req, res) => {
  try {
    const [rows] = await pool.query(
      `SELECT t.transaction_id, t.from_account_id, t.to_account_id, t.amount,
              t.type, t.status, t.description, t.created_at
       FROM transactions t
       WHERE t.from_account_id IN (SELECT account_id FROM accounts WHERE user_id = ?)
          OR t.to_account_id IN (SELECT account_id FROM accounts WHERE user_id = ?)
       ORDER BY t.created_at DESC, t.transaction_id DESC`,
      [req.user.user_id, req.user.user_id]
    );

    res.json(rows);
  } catch (err) {
    console.error('GetMyTransactions error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};
