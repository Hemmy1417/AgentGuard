# Judge round - 21 September 2026

The judges asked for matching updated source and deployment that:

1. make the delivery deadline and cure rule consequential, and remove the race
   between a late delivery and the terminal buyer-refund path;
2. limit each readjudication to the prior adjudication's evidence plus exactly
   the new evidence named and authorised by that appeal - the readjudication
   was reading every evidence item later committed to the agreement, including
   items the appeal did not name.

Both findings were accurate, confirmed by reading the code before any change.

## 1. The deadline and the cure period

**What was wrong.** `submit_delivery` accepted a delivery at any time while the
agreement was `FUNDED`. The no-delivery refund opened only after the deadline,
the cure period **and** the stall window. So after the cure period a seller could
still deliver at any moment until someone claimed the refund - whichever
transaction landed first won - and the deadline itself changed nothing:
`DEADLINE_MISSED` was recorded and moved no money.

**What changed.**

- `submit_delivery` refuses a delivery after the deadline plus the cure period
  (`_delivery_closes`): "the deadline and its cure period closed at ...; no
  delivery is accepted, and the buyer's refund is due".
- `claim_stalled_agreement` opens the `NO_DELIVERY` refund the first second after
  that same boundary. The stall window no longer sits between them. A delivery
  is accepted at or before the boundary, the refund only after it, so the two
  can never both happen and neither waits on the other.
- A delivery inside the cure period stands, and from then on only the
  delivered-agreement routes remain. `DEADLINE_MISSED` now records that case: a
  delivery after the deadline, inside the cure period. A delivery after the cure
  period cannot exist.
- `settlement_status` reports a funded agreement as claimable from the same
  second.

**Tests** (`tests/direct/test_appeals.py`, `tests/direct/test_adversarial_cases.py`):
the refund refused at the last second of the cure period and granted one second
later; a delivery one second after the cure period refused, the escrow untouched,
the refund then paid; the mirror - a delivery at the last second of the cure
period stands and the no-delivery refund is refused; a delivery at the deadline
recorded on time and one inside the cure period recorded as late.

## 2. What a readjudication reads

**What was wrong.** `request_readjudication` built its items from every evidence
item committed to the agreement. Anything either party committed after the first
round - including items no appeal named - reached the second panel.

**What changed.** `request_readjudication` reads exactly the appealed record's
evidence, in its order, followed by exactly the items the appeal named
(`submit_appeal` already restricts those to the appellant's own evidence that no
round has read). The new record carries `evidence_scope`, with both lists. A
second appeal builds on the readjudication it appeals, so its prior evidence is
that round's.

**Tests** (`tests/direct/test_appeals.py`): after the first round the buyer
commits one item and the seller two; the seller's appeal names one. The
readjudication reads the first round's items plus that one, `evidence_scope`
says so, and neither un-named item is read.

## Mutations

Six mutations pin the new guards, each killed by the suite behind an
accept-control (`deploy/mutation_judge_fix.txt`): a delivery accepted after the
cure period; the delivery window ignoring the cure period; a stalled claim before
the seller's time is up; a readjudication reading every item committed since; a
readjudication dropping what the appeal added; a delivery inside the cure period
not recorded as late.

## The updated deployment

| Item | Value |
|---|---|
| Contract | `0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c` |
| Explorer | https://explorer-studio.genlayer.com/address/0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c |
| Deploy transaction | `0xb362ac3098883e51d43faabf8239dae2ff501a91b5596232f470912135761762`, FINALIZED, leader SUCCESS, votes AGREE, AGREE, IDLE, AGREE, IDLE |
| Source | `contracts/agentguard.py` at commit `c5dd0c4`, sha256 `cedeff5fbe20e4a4c5a4464fd12dd7e56dde914f5e40263abc7f127b0410ffde`; byte-identical to the deployed source |
| Superseded | `0x972AdCD7e9ac0D93FD8D678c9fF59cf5B714b4c2`, listed with its reason under `other_addresses` in `deploy/deployment.json`; its live transcript is in `deploy/superseded/0x972AdCD7/` |

Phases A and C of `scripts/live_scenarios.py` ran on `0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c`: 54 transactions, every asserted check held (`deploy/live_scenarios_transcript.json`, `deploy/live_run_judge2.log`).

| What | On chain |
|---|---|
| A readjudication reads only the appealed evidence plus what the appeal named | after the first round the buyer committed `EV-000003` and the seller `EV-000004`, which no appeal named; the seller's appeal named `EV-000005`, `EV-000006`. The [readjudication](https://explorer-studio.genlayer.com/tx/0x637d626c192b2fcfc3c2b1838bef5494f78c6301a37d5bd5dfdd35a7dd2206d8) read `EV-000001`, `EV-000002` (the first round's) plus the two named items, and neither un-named item; its record's `evidence_scope` lists both parts |
| The readjudication settled | FULFILLED, 10000 bps; [finalized](https://explorer-studio.genlayer.com/tx/0x1f97e9ebe59230f0d4fe8a52474055b07ab92c9ad62aa747395e1cf6ae36c3c2) after the appeal window; the seller's wallet rose by exactly 0.05 GEN on [withdrawal](https://explorer-studio.genlayer.com/tx/0xc45132d200c01e03c37fbe528e63be26b70fb470ff46de03d457453dddd1ebd9) |
| A delivery after the cure period is refused | [submit_delivery](https://explorer-studio.genlayer.com/tx/0x6b35b74d966a3549d189de924a4e45d38679e3e93a2ad6dec0d5aa05114fbbf4) about 20 seconds after the deadline plus the cure period (the Direct Mode suite pins the exact second): "the deadline and its cure period closed at ...; no delivery is accepted, and the buyer's refund is due"; the agreement stayed funded |
| The refund opens at the same boundary | [claim_stalled_agreement](https://explorer-studio.genlayer.com/tx/0x37c7118b011589228906038a0c01baf016d65e970e94e93f4587924fa72b789a) then refunded the buyer in full (`NO_DELIVERY`), with no stall window in between; the buyer [withdrew](https://explorer-studio.genlayer.com/tx/0xd288054e650bdaf5fdf8f95e8160ccb97641cea44294bcc323629b07ea4dadda) 0.05 GEN |
| The mirror: a delivery inside the cure period stands | [delivered](https://explorer-studio.genlayer.com/tx/0xaaad2c4ce0e0d5702d62415ff23fa02ebdb297b62d6d41389ca8cdc7098d710d) after the deadline, inside a 900 s cure period, and accepted; the no-delivery [refund was refused](https://explorer-studio.genlayer.com/tx/0x79c376e730f17cb654cf0843578c1a4e01fbf43e5eb8330ef6c648aa095a3024); the buyer [accepted](https://explorer-studio.genlayer.com/tx/0xd23d4e542bf62056707e28c1e46fe342c49b7e398f742dec4da27228ca33baba) and the seller withdrew 0.05 GEN |
| Refusals | 15 attempts refused, each with its sentence |

The first round of phase A read INSUFFICIENT_EVIDENCE where the script expected PARTIALLY_FULFILLED - a panel reading, recorded rather than asserted, and the same first-round reading the superseded deployment's live run recorded; the escrow was held either way. Phase B, the 26-case adversarial suite, was not re-run on this deployment: its engine path is unchanged by this round except that `DEADLINE_MISSED` now names cure-period deliveries, which the Direct Mode suite covers.

Integration against the deployment (`python -m pytest tests/integration -q`): 6 passed, 1 skipped (the opt-in live write).

## One further finding, recorded and not changed here

Reading the superseded deployment's balance before retiring it showed 49 999 999
999 999 999 atto on chain while its ledger accounts for no escrow and no credit.
The value came from the live run's refusal of a funding one wei short of the
price: `fund_escrow` refuses by raising, and StudioNet keeps the value of a
payable transaction that raises. No method can move it. The same refusal behaved the
same way in this round's live run: the new deployment's ledger accounts for no escrow
and no credit while its chain balance is 49 999 999 999 999 999 atto. The fix - return a refused deposit as a
claimable credit instead of raising - is outside what this round asked for, so it
is reported rather than made.
