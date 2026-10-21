// Shared input validators. Return a clean value, or null when invalid.

// Positive integer id, from a number or a digit-only string (max 10 digits)
exports.parseId = (v) => {
  if (typeof v === 'number' && Number.isInteger(v) && v > 0) return v;
  if (typeof v === 'string' && /^[1-9]\d{0,9}$/.test(v)) return Number(v);
  return null;
};

// Money amount: > 0, at most 13 integer digits and 2 decimals. Returns a string like "100.50".
exports.parseAmount = (v) => {
  let s;
  if (typeof v === 'number' && Number.isFinite(v)) s = String(v);
  else if (typeof v === 'string') s = v.trim();
  else return null;
  if (!/^\d{1,13}(\.\d{1,2})?$/.test(s)) return null;
  if (Number(s) <= 0) return null;
  return s;
};

// Compare money safely in whole cents
exports.toCents = (v) => Math.round(Number(v) * 100);

// Largest value a DECIMAL(15,2) balance column can hold: 9,999,999,999,999.99, in cents
exports.MAX_BALANCE_CENTS = 999999999999999;

exports.isEmail = (v) =>
  typeof v === 'string' && v.length <= 100 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);

exports.isPhone = (v) => typeof v === 'string' && /^\d{7,15}$/.test(v);
