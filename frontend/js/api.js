const API_BASE = 'http://localhost:5000/api';

function getToken() {
  return localStorage.getItem('token');
}

function setToken(token) {
  localStorage.setItem('token', token);
}

function clearToken() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
}

function getUser() {
  const u = localStorage.getItem('user');
  return u ? JSON.parse(u) : null;
}

function setUser(user) {
  localStorage.setItem('user', JSON.stringify(user));
}

// Turns text into something safe to put inside innerHTML (prevents stored XSS)
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

// Generic request wrapper
async function apiRequest(endpoint, method = 'GET', body = null, requireAuth = true) {
  const headers = { 'Content-Type': 'application/json' };

  if (requireAuth) {
    const token = getToken();
    if (!token) {
      window.location.href = 'login.html';
      return;
    }
    headers['Authorization'] = `Bearer ${token}`;
  }

  const options = { method, headers };
  if (body) options.body = JSON.stringify(body);

  const res = await fetch(`${API_BASE}${endpoint}`, options);
  const data = await res.json();

  // Expired / invalid / revoked token on a protected call: log out and go to the login page
  if (res.status === 401 && requireAuth) {
    clearToken();
    window.location.href = 'login.html';
    throw new Error(data.error || 'Session expired');
  }

  if (!res.ok) {
    throw new Error(data.error || 'Something went wrong');
  }

  return data;
}

// Redirect to login if not authenticated (call at top of protected pages)
function requireAuthOrRedirect() {
  if (!getToken()) {
    window.location.href = 'login.html';
  }
}