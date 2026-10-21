const express = require('express');
const router = express.Router();
const adminController = require('../controllers/adminController');
const { verifyToken, requireAdmin } = require('../middleware/authMiddleware');

// All admin routes require valid token + admin role
router.use(verifyToken, requireAdmin);

router.get('/stats', adminController.getStats);
router.get('/users', adminController.getAllUsers);
router.get('/accounts', adminController.getAllAccounts);
router.patch('/accounts/:id/status', adminController.updateAccountStatus);
router.get('/transactions', adminController.getAllTransactions);
router.get('/audit-log', adminController.getAuditLog);

module.exports = router;