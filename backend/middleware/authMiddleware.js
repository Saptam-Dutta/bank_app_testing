const jwt = require('jsonwebtoken');
const pool = require('../config/db');
require('dotenv').config();

// Verifies token, then re-reads the user from the database so that deleted users
// and role changes take effect immediately instead of after token expiry.
exports.verifyToken = async (req, res, next) => {
  const authHeader = req.headers['authorization'];

  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'No token provided' });
  }

  const token = authHeader.split(' ')[1];

  let decoded;
  try {
    decoded = jwt.verify(token, process.env.JWT_SECRET, { algorithms: ['HS256'] });
  } catch (err) {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }

  try {
    const [rows] = await pool.query(
      'SELECT user_id, email, role FROM users WHERE user_id = ?',
      [decoded.user_id]
    );
    if (rows.length === 0) {
      return res.status(401).json({ error: 'User no longer exists' });
    }
    req.user = { user_id: rows[0].user_id, email: rows[0].email, role: rows[0].role };
    next();
  } catch (err) {
    console.error('verifyToken error:', err.message);
    return res.status(500).json({ error: 'Server error' });
  }
};

// Restricts route to admin role only
exports.requireAdmin = (req, res, next) => {
  if (!req.user || req.user.role !== 'admin') {
    return res.status(403).json({ error: 'Admin access required' });
  }
  next();
};
