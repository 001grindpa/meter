```markdown
# Meter

Meter holds borrower collateral against a public rate threshold. The lender is paid only if two rate pages show the same breach inside the window. One page is not enough.

- Network: GenLayer StudioNet
- Chain ID: 61999 (0xf22f)
- Contract: 0x99BCE15a3cC7C1AEbF6deFACc0C12C6De2Bcb5d5
- Explorer: https://explorer-studio.genlayer.com/address/0x99BCE15a3cC7C1AEbF6deFACc0C12C6De2Bcb5d5

Source: `contracts/Meter.py`. Direct tests: `tests/direct/test_meter.py`.

## What it does

A borrower opens a position with collateral, a lender, an asset, a threshold, a date window, and two rate URLs. Liquidation can run from `window_end` until the day before `release_after`. Both pages must print a breach for that window. If they do, the collateral goes to the lender. If they do not, the position stays locked. On `release_after`, anyone can return the collateral to the borrower.

## Methods

- `open_position(lender, asset, threshold, window_start, window_end, rate_url_a, rate_url_b)` payable. Returns the id.
- `liquidate(position_id)` on or after `window_end`, and before `release_after`.
- `release(position_id)` on or after `release_after`.
- `get_position(position_id)`
- `get_position_count()`
- `get_reserved_collateral()`

`release_after` is stored as `window_end` plus one UTC day. It is not an argument.

## Rules

- Borrower and lender must be different addresses.
- Collateral must be greater than zero.
- `window_start` and `window_end` must be real `YYYY-MM-DD` dates, with `window_end` on or after `window_start`.
- Both rate URLs must be HTTPS, allowlisted, and on different hosts.
- `SAFE`, `UNKNOWN`, and `DISAGREE` leave the position `LOCKED`.
- `LIQUIDATED` means both pages showed a breach and the collateral went to the lender.
- `RELEASED` means the grace day passed and the collateral went back to the borrower.

## Tests

The direct tests cover a borrower set as lender, distinct rate hosts, impossible dates, early liquidation and release, release blocked on `window_end`, one release after `release_after`, a single-host disagreement, and payment to the lender on a dual breach.
```