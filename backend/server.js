require('dotenv').config();

if (!process.env.JWT_SECRET) {
  console.error('JWT_SECRET is not set in .env. Refusing to start.');
  process.exit(1);
}
if (process.env.JWT_SECRET.startsWith('change_this')) {
  console.warn('WARNING: JWT_SECRET is still the placeholder value. Set a long random secret in .env.');
}

const app = require('./app');

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
