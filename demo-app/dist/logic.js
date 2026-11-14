// All money is integer centavos. No floats in the splitting or settling math.

export function parseMoney(text) {
  const m = /^\s*(\d{1,12})(?:[.,](\d{1,2}))?\s*$/.exec(String(text).replace(/,(?=\d{3}\b)/g, ''));
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0') || 0);
}

// Percent to hundredths of a percent (50 -> 5000). Null if not a plain number.
export function parsePercent(text) {
  const m = /^\s*(\d{1,3})(?:\.(\d{1,2}))?\s*$/.exec(String(text));
  if (!m) return null;
  return Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0') || 0);
}

export function formatMoney(cents) {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  const whole = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+$)/g, ',');
  return `${sign}${whole}.${String(abs % 100).padStart(2, '0')}`;
}

// Equal split: everyone gets the floor, leftover centavos go one each to the first people.
export function splitEqual(cents, n) {
  const base = Math.floor(cents / n);
  const extra = cents - base * n;
  return Array.from({ length: n }, (_, i) => base + (i < extra ? 1 : 0));
}

// Percent split: floor each share, then hand leftover centavos to the largest
// fractional remainders (ties go to the earlier person). bps sum must be 10000.
export function splitPercent(cents, bps) {
  const parts = bps.map((bp, i) => ({ i, floor: Math.floor((cents * bp) / 10000), frac: (cents * bp) % 10000 }));
  let left = cents - parts.reduce((s, p) => s + p.floor, 0);
  const order = [...parts].sort((a, b) => b.frac - a.frac || a.i - b.i);
  const out = parts.map((p) => p.floor);
  for (const p of order) {
    if (left <= 0) break;
    out[p.i] += 1;
    left -= 1;
  }
  return out;
}

// Bill shape: { id, name, amount, payer, shares: { personId: cents } }
export function balances(people, bills, paid = []) {
  const bal = Object.fromEntries(people.map((p) => [p.id, 0]));
  for (const b of bills) {
    bal[b.payer] = (bal[b.payer] ?? 0) + b.amount;
    for (const [id, c] of Object.entries(b.shares)) bal[id] = (bal[id] ?? 0) - c;
  }
  for (const t of paid) {
    bal[t.from] = (bal[t.from] ?? 0) + t.amount;
    bal[t.to] = (bal[t.to] ?? 0) - t.amount;
  }
  return bal;
}

// Fewest payments: split non-zero balances into the most groups that each sum to zero
// (a group of k people needs k-1 payments). Exact for up to 16 people, greedy beyond.
export function settle(people, bills, paid = []) {
  const bal = balances(people, bills, paid);
  const items = Object.entries(bal).filter(([, v]) => v !== 0).map(([id, v]) => ({ id, v }));
  const groups = items.length <= 16 ? bestGroups(items) : [items];
  const payments = [];
  for (const g of groups) {
    const debt = g.filter((x) => x.v < 0).map((x) => ({ ...x })).sort((a, b) => a.v - b.v);
    const cred = g.filter((x) => x.v > 0).map((x) => ({ ...x })).sort((a, b) => b.v - a.v);
    let d = 0, c = 0;
    while (d < debt.length && c < cred.length) {
      const amt = Math.min(-debt[d].v, cred[c].v);
      payments.push({ from: debt[d].id, to: cred[c].id, amount: amt });
      debt[d].v += amt;
      cred[c].v -= amt;
      if (debt[d].v === 0) d++;
      if (cred[c].v === 0) c++;
    }
  }
  return payments;
}

function bestGroups(items) {
  const n = items.length;
  if (n === 0) return [];
  const full = (1 << n) - 1;
  const sum = new Array(full + 1).fill(0);
  for (let m = 1; m <= full; m++) {
    const low = 31 - Math.clz32(m & -m);
    sum[m] = sum[m & (m - 1)] + items[low].v;
  }
  const best = new Array(full + 1).fill(-1); // max number of zero-sum groups inside mask
  const pick = new Array(full + 1).fill(0);
  best[0] = 0;
  for (let m = 1; m <= full; m++) {
    const lowBit = m & -m;
    for (let s = m; s; s = (s - 1) & m) {
      if (!(s & lowBit) || sum[s] !== 0 || best[m ^ s] < 0) continue;
      if (best[m ^ s] + 1 > best[m]) { best[m] = best[m ^ s] + 1; pick[m] = s; }
    }
  }
  const groups = [];
  for (let m = full; m; m ^= pick[m]) {
    const g = [];
    for (let i = 0; i < n; i++) if (pick[m] & (1 << i)) g.push(items[i]);
    groups.push(g);
  }
  return groups;
}
