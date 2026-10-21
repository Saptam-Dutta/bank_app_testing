const pool = require('../config/db');

exports.getAllBranches = async (req, res) => {
  try {
    const [rows] = await pool.query('SELECT branch_id, branch_name, ifsc_code, address FROM branches ORDER BY branch_name');
    res.json(rows);
  } catch (err) {
    console.error('GetAllBranches error:', err.message);
    res.status(500).json({ error: 'Server error' });
  }
};