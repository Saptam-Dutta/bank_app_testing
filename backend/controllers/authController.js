const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const pool = require('../config/db');
const { isEmail, isPhone } = require('../utils/validators');
require('dotenv').config();

// Hash used to burn equal time when the email is unknown (prevents user enumeration by timing)
const DUMMY_HASH = bcrypt.hashSync('dummy-password-for-timing', 10);

// ==========================
// REGISTER
// ==========================
exports.register = async (req, res) => {
  const { name, email, password, phone } = req.body || {};

  if (typeof name !== 'string' || typeof email !== 'string' || typeof password !== 'string'
      || !name.trim() || !email || !password) {
    return res.status(400).json({ error: 'Name, email, and password are required' });
  }
  if (name.trim().length > 100) {
    return res.status(400).json({ error: 'Name must be at most 100 characters' });
  }
  if (!isEmail(email)) {
    return res.status(400).json({ error: 'Invalid email format' });
  }
  // bcrypt only uses the first 72 bytes
  if (password.length < 8 || Buffer.byteLength(password) > 72) {
    return res.status(400).json({ error: 'Password must be 8 to 72 characters' });
  }
  if (phone !== undefined && phone !== null && phone !== '' && !isPhone(phone)) {
    return res.status(400).json({ error: 'Phone must be 7 to 15 digits' });
  }

  try {
    const password_hash = await bcrypt.hash(password, 10);

    const [result] = await pool.query(
      'INSERT INTO users (name, email, password_hash, phone, role) VALUES (?, ?, ?, ?, ?)',
      [name.trim(), email.toLowerCase(), password_hash, phone || null, 'customer']
    );

    res.status(201).json({
      message: 'User registered successfully',
      user_id: result.insertId
    });
  } catch (err) {
    // UNIQUE(email) is the real guard, so concurrent registrations get 409, not 500
    if (err.code === 'ER_DUP_ENTRY') {
      return res.status(409).json({ error: 'Email already registered' });
    }
    console.error('Register error:', err.message);
    res.status(500).json({ error: 'Server error during registration' });
  }
};

// ==========================
// LOGIN
// ==========================
exports.login = async (req, res) => {
  const { email, password } = req.body || {};

  if (typeof email !== 'string' || typeof password !== 'string' || !email || !password) {
    return res.status(400).json({ error: 'Email and password are required' });
  }

  try {
    const [rows] = await pool.query('SELECT * FROM users WHERE email = ?', [email.toLowerCase()]);
    const user = rows[0];

    // Always run bcrypt, even for unknown emails
    const match = await bcrypt.compare(password, user ? user.password_hash : DUMMY_HASH);

    if (!user || !match) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    const token = jwt.sign(
      { user_id: user.user_id, email: user.email, role: user.role },
      process.env.JWT_SECRET,
      { expiresIn: '2h', algorithm: 'HS256' }
    );

    res.json({
      message: 'Login successful',
      token,
      user: {
        user_id: user.user_id,
        name: user.name,
        email: user.email,
        role: user.role
      }
    });
  } catch (err) {
    console.error('Login error:', err.message);
    res.status(500).json({ error: 'Server error during login' });
  }
};

// ==========================
// GET CURRENT USER (protected)
// ==========================
exports.getMe = async (req, res) => {
  try {
    const [rows] = await pool.query(
      'SELECT user_id, name, email, phone, role, created_at FROM users WHERE user_id = ?',
      [req.user.user_id]
    );

    if (rows.length === 0) {
      return res.status(404).json({ error: 'User not found' });
    }

    res.json(rows[0]);
  } catch (err) {
    console.error('GetMe error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};

// ==========================
// UPDATE PROFILE (protected)
// ==========================
exports.updateProfile = async (req, res) => {
  const { name, phone } = req.body || {};

  if (typeof name !== 'string' || !name.trim()) {
    return res.status(400).json({ error: 'Name is required' });
  }
  if (name.trim().length > 100) {
    return res.status(400).json({ error: 'Name must be at most 100 characters' });
  }
  if (phone !== undefined && phone !== null && phone !== '' && !isPhone(phone)) {
    return res.status(400).json({ error: 'Phone must be 7 to 15 digits' });
  }

  try {
    await pool.query(
      'UPDATE users SET name = ?, phone = ? WHERE user_id = ?',
      [name.trim(), phone || null, req.user.user_id]
    );

    const [rows] = await pool.query(
      'SELECT user_id, name, email, phone, role, created_at FROM users WHERE user_id = ?',
      [req.user.user_id]
    );

    res.json({ message: 'Profile updated successfully', user: rows[0] });
  } catch (err) {
    console.error('UpdateProfile error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};
