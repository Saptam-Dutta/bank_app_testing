requireAuthOrRedirect();

const user = getUser();
document.getElementById('welcomeMsg').textContent = `Hi, ${user.name}`;

document.getElementById('logoutBtn').addEventListener('click', () => {
  clearToken();
  window.location.href = 'login.html';
});

let myAccounts = [];

// ==========================
// LOAD ACCOUNTS
// ==========================
async function loadAccounts() {
  try {
    myAccounts = await apiRequest('/accounts');
    renderAccounts();
    populateAccountDropdowns();
    document.getElementById('accountsLoading').classList.add('hidden');
    document.getElementById('accountsList').classList.remove('hidden');
    document.getElementById('newAccountBtn').classList.remove('hidden');
  } catch (err) {
    console.error(err.message);
    document.getElementById('accountsLoading').textContent = 'Failed to load accounts.';
  }
}

function renderAccounts() {
  const list = document.getElementById('accountsList');
  list.innerHTML = '';

  if (myAccounts.length === 0) {
    list.innerHTML = '<p style="color:#777;">No accounts yet. Open one below.</p>';
    return;
  }

  myAccounts.forEach(acc => {
    const div = document.createElement('div');
    div.className = 'account-card';
    div.style.cursor = 'pointer';
    div.innerHTML = `
      <div>
        <div class="meta">Account #${acc.account_id} — ${escapeHtml(acc.account_type.toUpperCase())} — ${escapeHtml(acc.branch_name)}</div>
        <span class="badge ${escapeHtml(acc.status)}">${escapeHtml(acc.status)}</span>
        <div style="margin-top:6px;"><a href="#" class="view-statement-link" data-id="${acc.account_id}" style="font-size:13px; color:#14213d; font-weight:600;">View Statement →</a></div>
      </div>
      <div class="balance">₹${parseFloat(acc.balance).toFixed(2)}</div>
    `;
    list.appendChild(div);
  });

  document.querySelectorAll('.view-statement-link').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      sessionStorage.setItem('viewAccountId', link.dataset.id);
      window.location.href = 'account-details.html';
    });
  });
}

async function loadBranches() {
  try {
    const branches = await apiRequest('/branches');
    const select = document.getElementById('branchSelect');
    select.innerHTML = branches.map(b =>
      `<option value="${escapeHtml(b.branch_id)}">${escapeHtml(b.branch_name)} (${escapeHtml(b.ifsc_code)})</option>`
    ).join('');
  } catch (err) {
    console.error(err.message);
  }
}

function populateAccountDropdowns() {
  const options = myAccounts.map(acc =>
    `<option value="${escapeHtml(acc.account_id)}">Account #${escapeHtml(acc.account_id)} (${escapeHtml(acc.account_type)}) - ₹${parseFloat(acc.balance).toFixed(2)}</option>`
  ).join('');

  document.getElementById('depositAccount').innerHTML = options;
  document.getElementById('withdrawAccount').innerHTML = options;
  document.getElementById('transferFrom').innerHTML = options;
}

// ==========================
// NEW ACCOUNT
// ==========================
document.getElementById('newAccountBtn').addEventListener('click', () => {
  document.getElementById('newAccountSection').classList.toggle('hidden');
});

document.getElementById('newAccountForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const account_type = document.getElementById('accountType').value;
  const branch_id = document.getElementById('branchSelect').value;
  const errorBox = document.getElementById('newAccountError');
  errorBox.style.display = 'none';

  try {
    await apiRequest('/accounts', 'POST', { branch_id: parseInt(branch_id), account_type });
    document.getElementById('newAccountSection').classList.add('hidden');
    await loadAccounts();
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = 'block';
  }
});

// ==========================
// TABS
// ==========================
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.txn-form').forEach(f => f.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab + 'Form').classList.remove('hidden');
    clearTxnMessages();
  });
});

function clearTxnMessages() {
  document.getElementById('txnError').style.display = 'none';
  document.getElementById('txnSuccess').style.display = 'none';
}

function showTxnError(msg) {
  const box = document.getElementById('txnError');
  box.textContent = msg;
  box.style.display = 'block';
}

function showTxnSuccess(msg) {
  const box = document.getElementById('txnSuccess');
  box.textContent = msg;
  box.style.display = 'block';
}

// ==========================
// DEPOSIT
// ==========================
document.getElementById('depositForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  clearTxnMessages();
  const account_id = document.getElementById('depositAccount').value;
  const amount = document.getElementById('depositAmount').value;

  if (parseFloat(amount) <= 0) {
    showTxnError('Amount must be greater than zero.');
    return;
  }

  try {
    await apiRequest('/transactions/deposit', 'POST', { account_id, amount: parseFloat(amount) });
    showTxnSuccess('Deposit successful!');
    document.getElementById('depositForm').reset();
    await loadAccounts();
  } catch (err) {
    showTxnError(err.message);
  }
});

// ==========================
// WITHDRAW
// ==========================
document.getElementById('withdrawForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  clearTxnMessages();
  const account_id = document.getElementById('withdrawAccount').value;
  const amount = document.getElementById('withdrawAmount').value;

  if (parseFloat(amount) <= 0) {
    showTxnError('Amount must be greater than zero.');
    return;
  }

  try {
    await apiRequest('/transactions/withdraw', 'POST', { account_id, amount: parseFloat(amount) });
    showTxnSuccess('Withdrawal successful!');
    document.getElementById('withdrawForm').reset();
    await loadAccounts();
  } catch (err) {
    showTxnError(err.message);
  }
});

// ==========================
// TRANSFER
// ==========================
document.getElementById('transferForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  clearTxnMessages();
  const from_account_id = document.getElementById('transferFrom').value;
  const to_account_id = document.getElementById('transferTo').value;
  const amount = document.getElementById('transferAmount').value;
  const description = document.getElementById('transferDesc').value;

  if (parseInt(from_account_id) === parseInt(to_account_id)) {
    showTxnError('Cannot transfer to the same account.');
    return;
  }
  if (parseFloat(amount) <= 0) {
    showTxnError('Amount must be greater than zero.');
    return;
  }

  try {
    await apiRequest('/transactions/transfer', 'POST', {
      from_account_id: parseInt(from_account_id),
      to_account_id: parseInt(to_account_id),
      amount: parseFloat(amount),
      description
    });
    showTxnSuccess('Transfer successful!');
    document.getElementById('transferForm').reset();
    await loadAccounts();
  } catch (err) {
    showTxnError(err.message);
  }
});

// ==========================
// INIT
// ==========================
loadAccounts();
loadBranches();