requireAuthOrRedirect();

const user = getUser();

// Guard: redirect non-admins straight to the customer dashboard
if (!user || user.role !== 'admin') {
  window.location.href = 'dashboard.html';
}

document.getElementById('welcomeMsg').textContent = `Admin: ${user.name}`;

document.getElementById('logoutBtn').addEventListener('click', () => {
  clearToken();
  window.location.href = 'login.html';
});

// ==========================
// TABS
// ==========================
document.querySelectorAll('.admin-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.admin-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.admin-panel').forEach(p => p.classList.add('hidden'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab + 'Panel').classList.remove('hidden');
  });
});

// ==========================
// STATS
// ==========================
async function loadStats() {
  try {
    const stats = await apiRequest('/admin/stats');
    document.getElementById('statUsers').textContent = stats.totalUsers;
    document.getElementById('statAccounts').textContent = stats.totalAccounts;
    document.getElementById('statTxns').textContent = stats.totalTransactions;
    document.getElementById('statBalance').textContent = `₹${parseFloat(stats.totalBalance).toFixed(2)}`;
  } catch (err) {
    console.error(err.message);
  }
}

// ==========================
// USERS
// ==========================
async function loadUsers() {
  try {
    const users = await apiRequest('/admin/users');
    const tbody = document.getElementById('usersBody');
    tbody.innerHTML = users.map(u => `
      <tr>
        <td>${u.user_id}</td>
        <td>${escapeHtml(u.name)}</td>
        <td>${escapeHtml(u.email)}</td>
        <td>${escapeHtml(u.phone || '—')}</td>
        <td>${escapeHtml(u.role)}</td>
        <td>${new Date(u.created_at).toLocaleDateString()}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.error(err.message);
  }
}

// ==========================
// ACCOUNTS (with freeze/unfreeze/close actions)
// ==========================
async function loadAccounts() {
  try {
    const accounts = await apiRequest('/admin/accounts');
    const tbody = document.getElementById('accountsBody');
    tbody.innerHTML = accounts.map(a => `
      <tr>
        <td>${a.account_id}</td>
        <td>${escapeHtml(a.owner_name)} (${escapeHtml(a.owner_email)})</td>
        <td>${escapeHtml(a.account_type)}</td>
        <td>₹${parseFloat(a.balance).toFixed(2)}</td>
        <td><span class="badge ${escapeHtml(a.status)}">${escapeHtml(a.status)}</span></td>
        <td>${escapeHtml(a.branch_name)}</td>
        <td>
          ${renderStatusActions(a.account_id, a.status)}
        </td>
      </tr>
    `).join('');

    // Attach listeners after render
    document.querySelectorAll('.status-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const accId = btn.dataset.id;
        const newStatus = btn.dataset.status;
        try {
          await apiRequest(`/admin/accounts/${accId}/status`, 'PATCH', { status: newStatus });
          await loadAccounts();
          await loadStats();
        } catch (err) {
          alert(err.message);
        }
      });
    });
  } catch (err) {
    console.error(err.message);
  }
}

function renderStatusActions(accountId, currentStatus) {
  const buttons = [];
  if (currentStatus !== 'active') {
    buttons.push(`<button class="status-btn" data-id="${accountId}" data-status="active" style="width:auto; padding:4px 10px; font-size:12px; margin-right:4px;">Activate</button>`);
  }
  if (currentStatus !== 'frozen') {
    buttons.push(`<button class="status-btn secondary" data-id="${accountId}" data-status="frozen" style="width:auto; padding:4px 10px; font-size:12px; margin-right:4px; background:#856404;">Freeze</button>`);
  }
  if (currentStatus !== 'closed') {
    buttons.push(`<button class="status-btn secondary" data-id="${accountId}" data-status="closed" style="width:auto; padding:4px 10px; font-size:12px; background:#b71c1c;">Close</button>`);
  }
  return buttons.join('');
}

// ==========================
// TRANSACTIONS
// ==========================
async function loadTransactions() {
  try {
    const txns = await apiRequest('/admin/transactions');
    const tbody = document.getElementById('adminTxnsBody');
    tbody.innerHTML = txns.map(t => `
      <tr>
        <td>${new Date(t.created_at).toLocaleString()}</td>
        <td class="type-${escapeHtml(t.type)}">${escapeHtml(t.type.toUpperCase())}</td>
        <td>${t.from_account_id ?? '—'}</td>
        <td>${t.to_account_id ?? '—'}</td>
        <td>₹${parseFloat(t.amount).toFixed(2)}</td>
        <td>${escapeHtml(t.status)}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.error(err.message);
  }
}

// ==========================
// AUDIT LOG
// ==========================
async function loadAuditLog() {
  try {
    const logs = await apiRequest('/admin/audit-log');
    const tbody = document.getElementById('auditBody');
    tbody.innerHTML = logs.map(l => `
      <tr>
        <td>${new Date(l.changed_at).toLocaleString()}</td>
        <td>${l.account_id}</td>
        <td>${escapeHtml(l.owner_name)}</td>
        <td>${escapeHtml(l.action)}</td>
        <td>₹${parseFloat(l.old_balance).toFixed(2)}</td>
        <td>₹${parseFloat(l.new_balance).toFixed(2)}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.error(err.message);
  }
}

// ==========================
// INIT
// ==========================
loadStats();
loadUsers();
loadAccounts();
loadTransactions();
loadAuditLog();