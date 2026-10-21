requireAuthOrRedirect();

const user = getUser();
document.getElementById('welcomeMsg').textContent = `Hi, ${user.name}`;

document.getElementById('logoutBtn').addEventListener('click', () => {
  clearToken();
  window.location.href = 'login.html';
});

async function loadProfile() {
  try {
    const me = await apiRequest('/auth/me');
    document.getElementById('name').value = me.name;
    document.getElementById('email').value = me.email;
    document.getElementById('phone').value = me.phone || '';
    document.getElementById('role').value = me.role;
    document.getElementById('createdAt').value = new Date(me.created_at).toLocaleDateString();
  } catch (err) {
    console.error(err.message);
  }
}

document.getElementById('profileForm').addEventListener('submit', async (e) => {
  e.preventDefault();

  const name = document.getElementById('name').value;
  const phone = document.getElementById('phone').value;

  const errorBox = document.getElementById('errorMsg');
  const successBox = document.getElementById('successMsg');
  errorBox.style.display = 'none';
  successBox.style.display = 'none';

  try {
    const result = await apiRequest('/auth/me', 'PUT', { name, phone });
    setUser(result.user); // update localStorage copy too
    document.getElementById('welcomeMsg').textContent = `Hi, ${result.user.name}`;
    successBox.textContent = 'Profile updated successfully!';
    successBox.style.display = 'block';
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.style.display = 'block';
  }
});

loadProfile();