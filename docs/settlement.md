# Settlement

Money moves in exactly two places: `fund_escrow` takes it in, and `withdraw`
pays it out of a pull-payment ledger. Everything between is accounting the
contract does itself, from a verdict validators agreed on.

## The fulfillment level

`_levels` sums the weight of the non-optional criteria, and the weight of those
the round found SATISFIED:

```text
level = satisfied_weight * 100 // total_weight        (integer, floor)
```

UNVERIFIABLE weight counts for nobody: it neither earns the seller anything nor
proves the work was not done. It is tracked separately, and when its share
exceeds the policy's `unverifiable_weight_limit` the verdict becomes
INSUFFICIENT_EVIDENCE rather than a split computed from a level nobody can
stand behind.

## The verdict

`_derive` walks one ordered list. Everything above step 7 **holds** the escrow:
the agreement stays open, an appeal is possible, and the stalled-agreement path
is its terminal exit. No branch reads model prose.

| # | Condition | Verdict | Settles |
|---:|---|---|---|
| 1 | an allowed item was unreachable, or its bytes changed | `SOURCE_UNAVAILABLE` | no |
| 2 | an allowed item was oversized or malformed | `INCONCLUSIVE` | no |
| 3 | the panel's answer was not usable | `INCONCLUSIVE` | no |
| 4 | no untainted examined item, or fewer than the policy's minimum | `INSUFFICIENT_EVIDENCE` | no |
| 5 | the panel found fabrication, or text aimed at itself | `CONFLICTING_EVIDENCE` | no |
| 6 | a question whose answer could change the verdict came back undecided | `INCONCLUSIVE` | no |
| 7 | the buyer withheld input **and** the seller changed scope | `MUTUAL_FAULT` | yes |
| 8 | the buyer withheld what the work needed | `BUYER_NON_COOPERATION` | yes |
| 9 | a declared external dependency failed | `EXTERNAL_DEPENDENCY_FAILURE` | yes |
| 10 | the seller delivered a materially different service | `NOT_FULFILLED` | yes |
| 11 | too much criterion weight is unverifiable | `INSUFFICIENT_EVIDENCE` | no |
| 12 | level at or above `full_threshold` | `FULFILLED` | yes |
| 13 | level at or above `partial_threshold` | `PARTIALLY_FULFILLED` | yes |
| 14 | otherwise | `NOT_FULFILLED` | yes |

Both thresholds are inclusive: a level exactly at `full_threshold` is
FULFILLED, and one exactly at `partial_threshold` is PARTIALLY_FULFILLED at the
policy's floor.

Step 6 holds the escrow only for the five indicators whose answer appears in
the chain above - fabrication, injection, a withholding buyer, a failed
dependency, a substituted service (`OUTCOME_INDICATORS`, published by
`get_config`). `BUYER_CRITERIA_CHANGE` is not one of them: it records that the
buyer demanded more than the criteria, which is fault, not money. A live
readjudication found every criterion SATISFIED at 100/100 and still paid
nobody, because the panel had left that one question undecided - and the
stalled route would then have refunded the buyer for work the panel called
complete. An escrow may only be held by a question that could have moved it.

Two verdicts are never produced here. `SELLER_NON_PERFORMANCE` belongs to the
stalled route for an agreement that was funded and never delivered - an
adjudication cannot reach it, because a dispute can only follow a delivery.
`REJECTED` belongs to the buyer-silence route under a policy where silence is
not acceptance.

Fault is recorded separately from the money: `seller_fault_level` is FULL on
NOT_FULFILLED, PARTIAL on PARTIALLY_FULFILLED and MUTUAL_FAULT; `buyer_fault_level` is FULL on BUYER_NON_COOPERATION and PARTIAL
on MUTUAL_FAULT or whenever the panel found `BUYER_CRITERIA_CHANGE` - so a
buyer who moved the goalposts is recorded as at fault even in a round the
seller wins outright.

Confidence is LOW when no panel answered, MEDIUM when some criterion is
UNVERIFIABLE, HIGH otherwise.

## The split

`_seller_bps` is integer arithmetic over the agreed level and the policy both
agents bound themselves to. No model output reaches it.

```text
FULFILLED                    -> 10000
PARTIALLY_FULFILLED          -> min(10000, floor + (10000 - floor) * (level - low) // (high - low))
                                where low = partial_threshold, high = full_threshold,
                                floor = partial_seller_bps_at_threshold
NOT_FULFILLED                -> not_fulfilled_seller_bps
BUYER_NON_COOPERATION        -> buyer_non_cooperation_seller_bps
MUTUAL_FAULT                 -> mutual_fault_seller_bps
EXTERNAL_DEPENDENCY_FAILURE  -> external_failure_seller_bps
SELLER_NON_PERFORMANCE, REJECTED, every holding verdict -> 0
```

The partial share rises linearly from the policy's floor at the partial
threshold toward the whole escrow at the full threshold, and is clamped: a
level above the full threshold cannot buy more than the escrow, whatever
thresholds a policy sets.

`_split` turns basis points into wei:

```text
seller = escrow * bps // 10000
buyer  = escrow - seller
```

The remainder of the integer division goes to the buyer - it is their money
until a verdict says otherwise - and the two allocations sum to the escrow
exactly, by construction, for every bps value.

## Moving it

`_settle` is the only function that credits anyone, and it moves the escrow
whole or not at all:

```text
seller_atto < 0 or buyer_atto < 0              -> revert
seller_atto + buyer_atto != escrow             -> revert
escrow > escrow_total_atto                     -> revert (accounting inconsistent)
escrow_atto = 0; escrow_total -= escrow
credit(seller); credit(buyer); status = FINALIZED; route and amounts recorded
```

Eight call sites reach it, and `scripts/preflight.py` asserts that count:

| Route | Reached by | Split |
|---|---|---|
| `BUYER_ACCEPTED` | `accept_delivery` | the whole escrow to the seller, at once, with no consensus round - no panel is needed to agree with the agent who is paying |
| `ADJUDICATED` | `finalize_settlement`, and the same route inside `claim_stalled_agreement` | the standing adjudication's own allocation |
| `NO_DELIVERY` | `claim_stalled_agreement`, FUNDED past deadline + cure + stall | refund in full |
| `BUYER_SILENCE` | `claim_stalled_agreement`, DELIVERED past dispute + stall | the whole escrow to the seller when `silence_is_acceptance`, otherwise refund in full |
| `NO_ADJUDICATION` | `claim_stalled_agreement`, DISPUTED past stall | refund in full |
| `UNSETTLED_ADJUDICATION` | `claim_stalled_agreement`, ADJUDICATED with a holding verdict past appeal + stall | refund in full - an escrow never shown to be earned goes back to the agent who paid it |

`finalize_settlement` is permissionless but refuses while the appeal window is
open, while any appeal is waiting to be heard, and for any verdict that does
not settle. `claim_stalled_agreement` is permissionless and purely wall-clock:
every state that can hold escrow has an exit that needs no counterparty, so an
agent cannot strand the other's money by going quiet.

## The ledger

`_credit` adds to `credits[wallet]` and to `credits_total_atto`. `withdraw`
clears the caller's entry **before** emitting the transfer, so a repeat pays
nothing; the transfer goes out through an empty `@gl.evm.contract_interface`
proxy, which is the supported shape for paying a bare wallet.

`health_check` reports `escrow_held_atto` and `claimable_atto`. Their sum is
the contract's whole liability, and every settlement moves value from the first
to the second without changing the total.

## Appeals

Either agent may appeal the standing adjudication inside its window, naming
1-4 evidence items committed **after** that adjudication read the record, and
only its own. `request_readjudication` hears it: the same frozen terms, the same
policy version, the same escrow, the first round's evidence plus what the appeal
added. The appealed record is never modified - the new one names it in
`appeal_of` and carries a `changes` block with the verdict, level, bps and
allocation before and after, the added evidence, and the reason codes gained
and lost. The escrow has not moved at either point, so an appeal never has to
claw anything back.
