const express = require('express');
const router = express.Router();
const accountController = require('../controllers/accountController');
const { verifyToken } = require('../middleware/authMiddleware');

router.get('/', verifyToken, accountController.getMyAccounts);
router.get('/:id/statement', verifyToken, accountController.getStatement);
router.get('/:id', verifyToken, accountController.getAccountById);
router.post('/', verifyToken, accountController.createAccount);

module.exports = router;
