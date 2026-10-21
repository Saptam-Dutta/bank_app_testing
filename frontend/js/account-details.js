requireAuthOrRedirect();

const user = getUser();
document.getElementById('welcomeMsg').textContent = `Hi, ${user.name}`;

document.getElementById('logoutBtn').addEventListener('click', () => {
  clearToken();
  window.location.href = 'login.html';
});

// Get account ID from sessionStorage (set by dashboard.js when clicking "View Statement")
const accountId = sessionStorage.getItem('viewAccountId');

async function loadAccountDetails() {
  const loadingBox = document.getElementById('loadingBox');
  const content = document.getElementById('accountContent');
  const notFoundBox = document.getElementById('notFoundBox');

  if (!accountId) {
    loadingBox.classList.add('hidden');
    notFoundBox.classList.remove('hidden');
    return;
  }

  try {
    const account = await apiRequest(`/accounts/${accountId}`);

    // Render account summary
    document.getElementById('accountTitle').textContent = `Account #${account.account_id}`;
    document.getElementById('accountMeta').textContent =
      `${account.account_type.toUpperCase()} — ${account.branch_name} (${account.ifsc_code})`;

    const badge = document.getElementById('accountStatusBadge');
    badge.textContent = account.status;
    badge.className = `badge ${account.status}`;

    document.getElementById('accountBalance').textContent = `₹${parseFloat(account.balance).toFixed(2)}`;

    // Fetch all transactions, filter to this account
    const allTxns = await apiRequest('/transactions');
    const myTxns = allTxns.filter(t =>
      t.from_account_id === parseInt(accountId) || t.to_account_id === parseInt(accountId)
    );

    // Compute stats
    let totalDeposited = 0;
    let totalWithdrawn = 0;

    myTxns.forEach(t => {
      const amt = parseFloat(t.amount);
      if (t.type === 'deposit' && t.to_account_id === parseInt(accountId)) {
        totalDeposited += amt;
      } else if (t.type === 'withdrawal' && t.from_account_id === parseInt(accountId)) {
        totalWithdrawn += amt;
      } else if (t.type === 'transfer') {
        if (t.to_account_id === parseInt(accountId)) totalDeposited += amt;
        if (t.from_account_id === parseInt(accountId)) totalWithdrawn += amt;
      }
    });

    document.getElementById('totalDeposited').textContent = `₹${totalDeposited.toFixed(2)}`;
    document.getElementById('totalWithdrawn').textContent = `₹${totalWithdrawn.toFixed(2)}`;
    document.getElementById('txnCount').textContent = myTxns.length;

    // Render statement rows
    const tbody = document.getElementById('statementBody');
    if (myTxns.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:#777;">No transactions yet.</td></tr>';
    } else {
      tbody.innerHTML = myTxns.map(t => {
        const isOutgoing = t.from_account_id === parseInt(accountId);
        let counterparty = '—';
        if (t.type === 'transfer') {
          counterparty = isOutgoing ? `To Account #${t.to_account_id}` : `From Account #${t.from_account_id}`;
        } else if (t.type === 'deposit') {
          counterparty = 'Cash deposit';
        } else if (t.type === 'withdrawal') {
          counterparty = 'Cash withdrawal';
        }

        const sign = (t.type === 'withdrawal' || (t.type === 'transfer' && isOutgoing)) ? '−' : '+';
        const color = sign === '−' ? '#b71c1c' : '#1e7e34';

        return `
          <tr>
            <td>${new Date(t.created_at).toLocaleString()}</td>
            <td class="type-${escapeHtml(t.type)}">${escapeHtml(t.type.toUpperCase())}</td>
            <td>${counterparty}</td>
            <td style="color:${color}; font-weight:600;">${sign}₹${parseFloat(t.amount).toFixed(2)}</td>
            <td>${escapeHtml(t.description || '—')}</td>
          </tr>
        `;
      }).join('');
    }

    loadingBox.classList.add('hidden');
    content.classList.remove('hidden');

  } catch (err) {
    loadingBox.classList.add('hidden');
    notFoundBox.classList.remove('hidden');
    console.error(err.message);
  }
}

loadAccountDetails();