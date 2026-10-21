const express = require('express');
const router = express.Router();
const transactionController = require('../controllers/transactionController');
const { verifyToken } = require('../middleware/authMiddleware');

router.post('/deposit', verifyToken, transactionController.deposit);
router.post('/withdraw', verifyToken, transactionController.withdraw);
router.post('/transfer', verifyToken, transactionController.transfer);
router.get('/', verifyToken, transactionController.getMyTransactions);

module.exports = router;