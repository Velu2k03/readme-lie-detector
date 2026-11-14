import { parseMoney, parsePercent, formatMoney, splitEqual, splitPercent, settle } from './logic.js';

const KEY = 'hati:v1';
const empty = { people: [], bills: [], paid: [], nextId: 1 };

function load() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY));
    if (s && Array.isArray(s.people) && Array.isArray(s.bills)) return { ...empty, ...s };
  } catch {}
  return structuredClone(empty);
}
let state = load();
const save = () => localStorage.setItem(KEY, JSON.stringify(state));
const $ = (id) => document.getElementById(id);
const nameOf = (id) => state.people.find((p) => p.id === id)?.name ?? '?';
const el = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  e.append(...kids);
  return e;
};

// Per-person percent inputs live outside state; rebuilt whenever the people list or mode changes.
function renderBillPeople() {
  const box = $('bill-people');
  const checked = new Set([...box.querySelectorAll('input[type=checkbox]:checked')].map((c) => c.value));
  const pct = Object.fromEntries([...box.querySelectorAll('.pct')].map((i) => [i.dataset.id, i.value]));
  const first = box.childElementCount === 0;
  box.replaceChildren(el('legend', {}, 'Split between'));
  const percent = $('bill-mode').value === 'percent';
  for (const p of state.people) {
    const cb = el('input', { type: 'checkbox', value: p.id, checked: first || checked.has(p.id) });
    const label = el('label', {}, cb, p.name);
    if (percent) {
      label.append(el('input', { className: 'pct', inputMode: 'decimal', placeholder: '%', ariaLabel: `${p.name} percent`, value: pct[p.id] ?? '' }));
      label.lastChild.dataset.id = p.id;
    }
    box.append(label);
  }
}

function render() {
  $('people').replaceChildren(...state.people.map((p) => el('li', {}, p.name)));
  const payer = $('bill-payer');
  const keep = payer.value;
  payer.replaceChildren(...state.people.map((p) => el('option', { value: p.id }, p.name)));
  if (state.people.some((p) => p.id === keep)) payer.value = keep;
  renderBillPeople();

  $('bills').replaceChildren(...(state.bills.length ? state.bills.map((b) => {
    const del = el('button', { type: 'button', ariaLabel: `Delete ${b.name}` }, 'Delete');
    del.onclick = () => { state.bills = state.bills.filter((x) => x.id !== b.id); save(); render(); };
    const split = Object.entries(b.shares).map(([id, c]) => `${nameOf(id)} ${formatMoney(c)}`).join(', ');
    return el('li', {}, el('span', {}, `${b.name}: ${formatMoney(b.amount)} paid by ${nameOf(b.payer)} `, el('span', { className: 'muted' }, `(${split})`)), del);
  }) : [el('li', { className: 'muted' }, 'No bills yet')]));

  const payments = settle(state.people, state.bills, state.paid);
  $('settle').replaceChildren(payments.length
    ? el('ul', {}, ...payments.map((t) => {
      const btn = el('button', { type: 'button', ariaLabel: `Mark paid: ${nameOf(t.from)} pays ${nameOf(t.to)} ${formatMoney(t.amount)}` }, 'Mark as paid');
      btn.onclick = () => { state.paid.push(t); save(); render(); };
      return el('li', {}, el('span', {}, `${nameOf(t.from)} pays ${nameOf(t.to)} ${formatMoney(t.amount)}`), btn);
    }))
    : el('p', {}, 'All settled'));
}

$('person-form').onsubmit = (e) => {
  e.preventDefault();
  const name = $('person-name').value.trim();
  if (!name) { $('person-error').textContent = 'Enter a name'; return; }
  if (state.people.some((p) => p.name.toLowerCase() === name.toLowerCase())) { $('person-error').textContent = 'That person is already added'; return; }
  $('person-error').textContent = '';
  state.people.push({ id: 'p' + state.nextId++, name });
  $('person-name').value = '';
  save(); render();
};

$('bill-mode').onchange = renderBillPeople;

$('bill-form').onsubmit = (e) => {
  e.preventDefault();
  const err = (m) => { $('bill-error').textContent = m; };
  const amount = parseMoney($('bill-amount').value);
  if (amount === null || amount <= 0) return err('Enter an amount greater than 0');
  const name = $('bill-name').value.trim();
  if (!name) return err('Enter a bill name');
  const payer = $('bill-payer').value;
  if (!payer) return err('Add people first');
  const rows = [...$('bill-people').querySelectorAll('label')].filter((l) => l.querySelector('[type=checkbox]').checked);
  if (!rows.length) return err('Choose who shares this bill');
  const ids = rows.map((l) => l.querySelector('[type=checkbox]').value);
  let cents;
  if ($('bill-mode').value === 'percent') {
    const bps = rows.map((l) => parsePercent(l.querySelector('.pct').value));
    if (bps.includes(null) || bps.reduce((s, x) => s + x, 0) !== 10000) return err('Percentages must add up to 100');
    cents = splitPercent(amount, bps);
  } else {
    cents = splitEqual(amount, ids.length);
  }
  err('');
  state.bills.push({ id: 'b' + state.nextId++, name, amount, payer, shares: Object.fromEntries(ids.map((id, i) => [id, cents[i]])) });
  $('bill-name').value = '';
  $('bill-amount').value = '';
  save(); render();
};

render();
