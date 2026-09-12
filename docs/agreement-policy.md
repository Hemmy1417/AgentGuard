# The agreement and the settlement policy

Two documents govern every dispute. The **agreement** is what these two agents
owe each other; the **settlement policy** is the rule book they both bound
themselves to for turning an outcome into money. Both are JSON, both are stored
canonically, and both are covered by a hash the record carries.

## The settlement policy

Registered once by anyone (`register_policy`), then referenced by agreements.
Exactly these keys, no others (`POLICY_KEYS`, `_parse_policy`):

| Key | Bounds | Meaning |
|---|---|---|
| `name` | text, 80 | a label for humans |
| `full_threshold` | 1-100 | the fulfillment level at or above which the verdict is FULFILLED |
| `partial_threshold` | 1-100, `<= full_threshold` | the level at or above which PARTIALLY_FULFILLED is possible |
| `partial_seller_bps_at_threshold` | 0-10000 | the seller's share exactly at the partial threshold |
| `not_fulfilled_seller_bps` | 0-10000 | the seller's share on NOT_FULFILLED |
| `buyer_non_cooperation_seller_bps` | 0-10000 | the seller's share when the buyer withheld what the work needed |
| `mutual_fault_seller_bps` | 0-10000 | the seller's share when both are at fault |
| `external_failure_seller_bps` | 0-10000 | the seller's share when a declared dependency failed |
| `minimum_evidence_items` | 1-14 | how many examined, untainted items an adjudication needs before it may decide anything |
| `maximum_evidence_age_days` | 1-3650 | a structured item older than this is stale, and stale evidence is excluded |
| `unverifiable_weight_limit` | 0-100 | the share of criterion weight that may be UNVERIFIABLE before the verdict becomes INSUFFICIENT_EVIDENCE |
| `silence_is_acceptance` | bool | whether a buyer who neither accepts nor disputes pays, on the stalled route |
| `maximum_appeals` | 0-2 | appeals per agreement |

A policy is immutable. `publish_policy_version` creates a successor and marks
the previous one SUPERSEDED; `revoke_policy_version` deactivates one. Neither
touches an agreement that already froze a version: live escrow keeps the rules
it was funded under, and only new agreements see the new version. A revoked
version still settles the agreements that bound it.

The demo policy the fixtures and the live run use:

```json
{"name": "AgentGuard demo policy - data services",
 "full_threshold": 90, "partial_threshold": 40,
 "partial_seller_bps_at_threshold": 4000, "not_fulfilled_seller_bps": 0,
 "buyer_non_cooperation_seller_bps": 7500, "mutual_fault_seller_bps": 5000,
 "external_failure_seller_bps": 2500, "minimum_evidence_items": 1,
 "maximum_evidence_age_days": 30, "unverifiable_weight_limit": 40,
 "silence_is_acceptance": true, "maximum_appeals": 1}
```

## The agreement

Proposed by the buyer (`propose_agreement`), accepted by the seller
(`accept_agreement`). Exactly these keys (`TERMS_KEYS`, `_parse_terms`):

| Key | Bounds | Meaning |
|---|---|---|
| `service_description` | text, 1200 | what is to be done; scanned for injection and hidden text and refused if either is found |
| `deliverables` | 1-8 items, 400 each | the things to be handed over |
| `acceptance_criteria` | 1-10 criteria | how it will be judged (below) |
| `price_atto` | 1 - 10^24 | the escrow, in atto-GEN |
| `deadline` | ISO `YYYY-MM-DDTHH:MM:SSZ` | when delivery is due; must be in the future at both proposal and acceptance |
| `cure_period_seconds` | 60 - 2592000 | grace after the deadline before delivery counts as late |
| `dispute_window_seconds` | 60 - 2592000 | how long the buyer has to accept or dispute after delivery |
| `appeal_window_seconds` | 60 - 2592000 | how long either agent has to appeal an adjudication |
| `stall_window_seconds` | 60 - 2592000 | the extra wall-clock wait before a stalled agreement can be claimed |
| `evidence_sources` | 1 per category | the per-category source allowlist (see [evidence-policy.md](evidence-policy.md)) |
| `external_dependencies` | 0-4 | the third-party services the work depends on, by name |
| `policy_id` | identifier | the settlement policy, which must have an ACTIVE version |

### Acceptance criteria

Each criterion carries exactly `criterion_id`, `text`, `kind`, `weight`,
`evidence_categories`, `requires_buyer_input` and `external_dependency`.

| Kind | Scored | Meaning |
|---|---|---|
| `OBJECTIVE` | yes | a fact about the work that evidence can settle |
| `SUBJECTIVE` | yes | a judgment about the work, still grounded in quotes |
| `OPTIONAL` | no | an enhancement: it neither earns the seller anything nor costs them anything, and with no evidence in its categories it is simply NOT_APPLICABLE |

`weight` is 1-100 and the fulfillment level is the satisfied share of the
non-optional weight. An agreement whose criteria are all OPTIONAL is refused:
optional enhancements alone are not a standard.

`evidence_categories` names 1-4 categories, and **never** `AGENT_MESSAGE` - no
criterion may be decided by an agent's own words. Every named category must
appear in `evidence_sources`, so a criterion can never depend on evidence the
agreement does not source. `external_dependency`, when set, must be one the
agreement declares.

### What freezing means

`accept_agreement` computes

```text
terms_hash = sha256(canonical({schema, agreement_id, buyer, seller, terms, policy_hash}))
```

and stores it. From that moment the criteria, the sources, the windows, the
price and the policy version are fixed. Every consensus round carries the
`terms_hash` in its payload and the structural gate rejects a payload bound to
different terms, so a round can never be replayed against a different standard.
The panel prompt says so in as many words: *THE AGREEMENT is the whole standard
... nothing either party said afterwards adds a requirement or removes one.*
That single sentence, plus the frozen hash, is what defeats attacks 4, 7 and 30
in the [threat model](threat-model.md).

## Lifecycle

```text
PROPOSED --accept--> ACCEPTED --fund--> FUNDED --deliver--> DELIVERED
   |                    |                  |                   |
   cancel               cancel             |            accept_delivery -> FINALIZED
   v                    v                  |                   |
CANCELLED           CANCELLED              |             open_dispute
                                           |                   v
                                    claim_stalled         DISPUTED --request_adjudication--> ADJUDICATED
                                    (refund)                   |                                 |
                                                         claim_stalled                    appeal / readjudication
                                                          (refund)                                |
                                                                                    finalize_settlement -> FINALIZED
                                                                                    claim_stalled       -> FINALIZED
```

Every state that can hold escrow has a terminal exit that needs no
counterparty. See [settlement.md](settlement.md).

## Agents

`register_agent` records the calling wallet, up to 8 capability strings and a
hash over them. The agent id **is** the wallet: nobody can act as, or be judged
as, someone else, and no separate identity registry can be spoofed. Both
parties to an agreement must be registered agents, and an agent cannot contract
with itself.
