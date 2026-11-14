# Hati

Hati is a bill splitter for people who share a home. Add the people you
live with, add the bills you share, and Hati works out who owes whom.

## How it works

- Add people, then add bills. Each bill is split between the people you
  choose, either equally or by percentage.
- Open Settle up to see the fewest payments that settle everything.
- Mark a payment as paid when it is done. Delete a bill and the balances
  update at once.
- Your bills are saved in your browser, so they are still there after a
  reload.

## What Hati promises

An equal split never loses a centavo. 1,000.00 split between Ana, Ben and
Cy gives 333.34, 333.33 and 333.33.

A percentage split follows the same rule. 1,000.01 at 50, 30 and 20 percent
gives 500.01, 300.00 and 200.00.

Percentages must add up to 100. Otherwise you see "Percentages must add up
to 100" and the bill is not saved.

Settle up shows the fewest payments. If Ana pays Rent 900.00 and Ben pays
Electricity 300.00, both shared equally, Settle up shows exactly two
payments.

Marking a payment as paid removes it. When every payment is marked paid,
Settle up says "All settled".

Deleting a bill updates balances at once. Delete Electricity from the
example above and Ben pays Ana 300.00.

Your bills are still there after a reload.

An amount must be greater than 0. A blank, zero or negative amount shows
"Enter an amount greater than 0" and no bill is added.

## What Hati does not promise here

Loads instantly.

Your data never leaves your browser.

Works offline after the first load.

Run it with npm install and npm run dev.
