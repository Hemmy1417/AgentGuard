# Integration

AgentGuard is a primitive, not an application: an agent framework, a
marketplace or another contract drives it. This is the whole surface.

## The flow, in calls

| Step | Call | Who | Notes |
|---|---|---|---|
| 1 | `register_agent(capabilities_json)` | each agent, once | the agent id is the signing wallet |
| 2 | `register_policy(policy_json)` -> `SP-nnnnnn` | whoever sets the rules | see [agreement-policy.md](agreement-policy.md) |
| 3 | `propose_agreement(seller_wallet, terms_json)` -> `AG-nnnnnn` | buyer | nothing is frozen yet |
| 4 | `accept_agreement(agreement_id)` -> `terms_hash` | seller | everything is frozen here |
| 5 | `fund_escrow(agreement_id)` **payable** | buyer | send exactly `price_atto` |
| 6 | `submit_evidence(agreement_id, category, url, sha256, issuer, description)` -> `EV-nnnnnn` | either | nothing is fetched yet |
| 7 | `submit_delivery(agreement_id, evidence_ids, statement)` | seller | |
| 8a | `accept_delivery(agreement_id)` | buyer | settles in full, no consensus round |
| 8b | `open_dispute(agreement_id, claim, evidence_ids)` | buyer | inside the dispute window |
| 9 | `submit_counterclaim(agreement_id, statement, evidence_ids)` | seller | optional |
| 10 | `request_adjudication(agreement_id)` -> `AD-nnnnnn` | **anyone** | one consensus round; no money moves |
| 11 | `submit_appeal(agreement_id, reason, new_evidence_ids)` -> `AP-nnnnnn` | either | inside the appeal window, own evidence only |
| 12 | `request_readjudication(appeal_id)` -> `AD-nnnnnn` | **anyone** | a second round on the same escrow |
| 13 | `finalize_settlement(agreement_id)` | **anyone** | after the appeal window, if the verdict settles |
| 13' | `claim_stalled_agreement(agreement_id)` | **anyone** | the wall-clock exit for every other case |
| 14 | `withdraw()` -> atto paid | each agent | pull payment; the ledger is cleared first |

Steps 10, 12, 13, 13' and 14 are permissionless by design: an agent whose
counterparty goes quiet is never stuck, and nothing about who sends the
transaction changes the outcome.

## The reads a caller needs

`settlement_status(agreement_id, as_of)` answers everything in one call. A
view has no clock of its own, so the caller passes one (`as_of`, an ISO
timestamp); the window flags are computed against it.

```json
{"found": true, "agreement_id": "AG-000001", "status": "ADJUDICATED",
 "buyer_agent_id": "0x...", "seller_agent_id": "0x...",
 "terms_hash": "...", "policy_id": "SP-000001", "policy_version": 1,
 "escrow_atto": "50000000000000000",
 "verdict": "PARTIALLY_FULFILLED", "fulfillment_level": 66,
 "seller_fault_level": "PARTIAL", "buyer_fault_level": "NONE",
 "seller_bps": 7120,
 "payment_allocation_atto": "35600000000000000",
 "refund_allocation_atto": "14400000000000000",
 "settleable": true, "adjudication_id": "AD-000001",
 "appeal_window_open": true, "appeal_pending": false,
 "can_finalize_now": false, "can_claim_stalled_now": false,
 "finalized": false, "settled_seller_atto": "0", "settled_buyer_atto": "0",
 "settlement_route": "", "silence_is_acceptance": true}
```

| Read | Returns |
|---|---|
| `get_config()` | every enum, bound and the equivalence statement the contract enforces |
| `health_check()` | counts, `escrow_held_atto`, `claimable_atto` |
| `get_agreement(id)` | the stored agreement, its ids and timestamps |
| `get_adjudication(id)`, `get_latest_adjudication(agreement_id)` | the full record: findings, receipts, reason codes, allocation, `record_digest` |
| `get_evidence(id)`, `get_delivery(id)`, `get_dispute(id)` | what each party committed and said |
| `get_appeal(id)` | an appeal and the readjudication it produced |
| `get_claimable(wallet)` | what that wallet may withdraw now |
| `get_agreement_history(id, offset, limit)`, `list_agent_agreements(wallet, offset, limit)` | paged ids |
| `get_adversarial_case(id)`, `list_adversarial_cases(policy_id, version, offset, limit)` | the test engine |

Every view is keyed or paged; none scans an unbounded collection.

## From another contract

```python
guard = gl.get_contract_at(Address(AGENTGUARD_ADDRESS))
status = guard.view().settlement_status(agreement_id, gl.message_raw["datetime"])
if status["finalized"] and status["verdict"] == "FULFILLED":
    ...                      # release the buyer's own downstream obligation
```

Read `settleable` and `verdict` rather than inferring anything from the
amounts, and treat a holding verdict as "not yet", not as a refusal: the
escrow is still open for an appeal or a stalled claim.

## What a caller must get right

- **Money is atto-GEN.** `price_atto` is an integer; `fund_escrow` must carry
  exactly it. Every amount in a record is a decimal **string**, because JSON
  numbers cannot carry 10^18 safely.
- **Evidence must be hosted before an adjudication, not before a commitment.**
  The bytes at the URL must hash to the committed digest at the moment every
  validator fetches it. A host that changes the bytes makes the item
  `HASH_MISMATCH` and holds the escrow.
- **One dispute, one round.** `request_adjudication` runs a consensus round;
  it is not a view and it is not free of latency. Poll `settlement_status`
  rather than re-sending it.
- **Clocks are wall-clock and windows are in seconds**, at least 60 and at
  most 30 days. A caller passing `as_of` should use the chain's time, not the
  user's.
- **Nothing is retried for you.** A round that ends INCONCLUSIVE stays that
  way until someone appeals or the stalled window passes.

## What AgentGuard does not do

It does not hold identity, reputation or history beyond the agreements it
adjudicated; it does not price work, match agents, or execute the service; it
does not escrow anything but native GEN; and it does not decide anything
outside the agreement two agents assented to. A marketplace that needs
reputation can compute it from `list_agent_agreements` and the stored records,
which are immutable and digest-covered.
