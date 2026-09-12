# Architecture

AgentGuard is one GenLayer Intelligent Contract, `contracts/agentguard.py`. It
has no frontend and no backend. Two AI agents assent to an agreement, the buyer
escrows the price in GEN, the seller delivers evidence, and - only when the
buyer disputes - one consensus round produces an immutable adjudication that
the contract's own arithmetic turns into a split of that escrow.

## The decision

> Given the agreement these two agents assented to, and only evidence from the
> sources they froze at assent, was the service fulfilled - and what split of
> the escrow does that support?

## The boundary

| Decided by code (deterministic, identical on every node) | Decided by consensus (a model panel, compared finding by finding) |
|---|---|
| Identity: each agent IS a signing wallet | Whether each acceptance criterion is met by the delivered work |
| The agreement, its criteria and windows, hashed at assent (`terms_hash`) | Whether a deliverable is unusable for the purpose the criterion states |
| Which sources each category may come from | Whether a difference in form is a reasonable variation or a substitution |
| sha256 verification of every byte before anything reads it | Whether an evidence item shows fabrication inside its own content |
| Every number, read from structured issuer documents | Whether the buyer withheld something the agreement required of it |
| Injection markers, hidden text and hidden styling | Whether a declared external dependency failed outside both agents' control |
| Duplicate bytes, cross-agreement reuse, evidence about another job | Whether the buyer is demanding what the frozen criteria do not require |
| Deadlines, cure, dispute, appeal and stall windows | Whether text in an item or a statement is addressed to the panel |
| The fulfillment level, the verdict, both fault levels | |
| The seller's basis points, the payment, the refund, escrow conservation | |
| The ledger, appeals, and every state transition | |

The model is never asked for an amount, a percentage or a payment decision. It
returns findings with quotes; code turns findings into a verdict, and the
verdict into wei.

## State

| Map | Key | Holds |
|---|---|---|
| `agents` | wallet | capabilities, `metadata_hash`, status |
| `policies` | `policy_id@version` | owner, status (ACTIVE / SUPERSEDED / REVOKED), canonical definition, `policy_hash`, case ids |
| `policy_heads` | `policy_id` | latest version |
| `agreements` | `AG-nnnnnn` | both wallets, status, canonical terms, `terms_hash`, policy version and hash, price, escrow, every timestamp, both statements, evidence / delivery / adjudication / appeal ids, the settled amounts and route |
| `evidence` | `EV-nnnnnn` | agreement, party, category, canonical URL, sha256, issuer label, description, `committed_seq` |
| `adjudications` | `AD-nnnnnn` or `AC-nnnnnn-R1` | the full canonical record with `record_digest` |
| `appeals` | `AP-nnnnnn` | appellant, the adjudication appealed, the new evidence, status |
| `cases` | `AC-nnnnnn` | adversarial cases, their expectations and their observed results |
| `evidence_registry` | sha256 | `seq\|agreement_id` of the first commitment of those bytes |
| `party_agreements` | wallet | that agent's agreement ids, at most 24 |
| `credits` | wallet | claimable atto-GEN (the pull-payment ledger) |

`escrow_total_atto` and `credits_total_atto` are the two running totals
`health_check` reports; every settlement moves exactly between them. Every map
is keyed and every list is bounded; no view scans an unbounded collection.
Records are written once and never modified - a readjudication is a new record
that names the one it answers.

## One adjudication

```text
request_adjudication(agreement_id)            # permissionless, one round
  |
  |- code: status DISPUTED? terms and policy as frozen at assent
  |- code: items = every evidence item committed to this agreement, each with
  |        allowed/trusted from the agreement's own per-category prefixes
  |
  +- gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
  |    every node, independently:
  |      fetch each ALLOWED item; sha256 the raw bytes BEFORE reading them
  |      structured items -> integer facts (or UNPARSEABLE)
  |      every item -> agreement link, foreign agreement ids, injection
  |        markers, hidden text
  |      _plan: code indicators; which criteria are still open; whether the
  |        panel can change anything at all
  |      panel only if it can -> findings, each quote grounded in own bytes
  |    validator: gate the leader payload with its OWN texts, then compare
  |      rows, facts, scans, panel state and every finding's state and layer
  |
  |- code: gate the ratified payload again (_parse_payload)
  |- code: the registry -> CROSS_AGREEMENT_REUSE, in commitment order
  |- code: _derive -> level, verdict, fault levels, seller bps, the split
  +- store the record, arm the appeal window; NO money moves here
```

Money moves later, and only through `_settle`: at `accept_delivery`, at
`finalize_settlement` once the appeal window has closed, or on one of the four
`claim_stalled_agreement` routes. `withdraw` is the only transfer.

The panel is not convened when an allowed item could not be examined, when no
examined item survives the code taints, or when nothing is left to ask. The
record says which (`panel_state`, `panel_reason`), and a skipped panel never
becomes anyone's fault - the criteria it would have judged stay UNVERIFIABLE.

## Single file

The brief sketches `agreement.py`, `evidence.py`, `adjudication.py`,
`settlement.py` and `security.py`. A multi-file contract needs the
`py-genlayer-multi` runner; this contract pins the single-file runner StudioNet
runs and `genvm-lint check` validates
(`py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`). The file
keeps the same separation as sections, in this order: constants and enums;
generic helpers (canonical JSON, dates, URL admission, the untrusted-text scans,
word-level quote grounding); the settlement policy; the agreement; evidence and
structured facts; findings and the round plan; the nondeterministic procedure;
the structural gate; derivation (level, verdict, split, summary, receipts);
storage records; then the contract class. Every helper above the class is a pure
function the test suite calls directly.

## Where each brief requirement lives

| Brief | Symbol |
|---|---|
| Agent identity and capabilities | `register_agent`, `AgentProfile` |
| Settlement policy and versions | `_parse_policy`, `register_policy`, `publish_policy_version`, `revoke_policy_version` |
| Agreement, criteria, windows | `_parse_terms`, `_parse_criterion`, `propose_agreement`, `accept_agreement` |
| Escrow | `fund_escrow` (payable), `_settle`, `withdraw`, `_Payee` |
| Evidence item and admission | `submit_evidence`, `_evidence_input_error`, `_url_parts`, `_provenance` |
| Evidence receipt | `_receipts` |
| Delivery and dispute | `submit_delivery`, `accept_delivery`, `open_dispute`, `submit_counterclaim` |
| Adjudication | `request_adjudication`, `_adjudicate`, `_derive` |
| Fulfillment level and the split | `_levels`, `_seller_bps`, `_split` |
| Appeals and readjudication | `submit_appeal`, `request_readjudication` |
| Terminal exits | `finalize_settlement`, `claim_stalled_agreement` |
| Adversarial test case | `register_adversarial_case`, `run_adversarial_case`, `replay_adversarial_case` |
| Consensus | `_node_round`, `_parse_payload`, `_first_difference`, `_validator_decision` |
| Downstream reads | `settlement_status`, `get_latest_adjudication`, `get_claimable` |
