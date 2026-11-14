import test from 'node:test';
import assert from 'node:assert/strict';
import { splitEqual, splitPercent, parseMoney, formatMoney, settle } from '../src/logic.js';

test('equal split never loses a centavo', () => {
  assert.deepEqual(splitEqual(100000, 3), [33334, 33333, 33333]);
});
test('percent split follows the same rule', () => {
  assert.deepEqual(splitPercent(100001, [5000, 3000, 2000]), [50001, 30000, 20000]);
});
test('money parse and format', () => {
  assert.equal(parseMoney('1,000.01'), 100001);
  assert.equal(parseMoney('0'), 0);
  assert.equal(parseMoney('-5'), null);
  assert.equal(parseMoney(''), null);
  assert.equal(formatMoney(100001), '1,000.01');
});
const people = ['a', 'b', 'c'].map((id) => ({ id }));
const bill = (payer, amount) => ({ payer, amount, shares: Object.fromEntries(splitEqual(amount, 3).map((c, i) => [people[i].id, c])) });
test('two payments for rent + electricity', () => {
  assert.equal(settle(people, [bill('a', 90000), bill('b', 30000)]).length, 2);
});
test('delete electricity: Ben pays Ana 300.00', () => {
  const p = settle(people, [bill('a', 90000)]);
  assert.ok(p.some((x) => x.from === 'b' && x.to === 'a' && x.amount === 30000));
});
test('finds the zero-sum subgroup shortcut', () => {
  const ps = ['a', 'b', 'c', 'd'].map((id) => ({ id }));
  const bills = [
    { payer: 'a', amount: 100, shares: { b: 100 } },
    { payer: 'c', amount: 50, shares: { d: 50 } },
  ];
  assert.equal(settle(ps, bills).length, 2);
});
