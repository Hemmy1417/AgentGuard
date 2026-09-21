<p align="center"><img src="docs/assets/agentguard-mark.svg" width="140" alt="AgentGuard"/></p>

# AgentGuard - Adjudicated Trust for AI Agent-to-Agent Commerce

**A standalone GenLayer Intelligent Contract that holds the escrow between two AI agents, decides under validator consensus whether the service they agreed was delivered, and computes the split itself.**

Two agents that have never met agree a service: what is to be done, how it will be judged, from which sources evidence may come, by when, and for how much. The seller accepts, and everything is frozen and hashed. The buyer escrows the price in GEN. The seller delivers evidence bound to the sha256 of its exact bytes. If the buyer accepts, the seller is paid at once. If the buyer disputes, one consensus round has every validator fetch and hash-verify every allowed item, read every number in code, and answer only what needs reading - each finding carrying quotes every validator re-checks against its own bytes. Code then computes the fulfillment level, the verdict, the fault levels and the split, to the wei.

No model output ever reaches an amount.

Canonical deployment: [`0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c`](https://explorer-studio.genlayer.com/address/0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c) on GenLayer StudioNet, byte-identical to `contracts/agentguard.py` at commit `c5dd0c4`. It answers the judge round of 21 September 2026 - [`docs/judge-round.md`](docs/judge-round.md).

## At a glance

| Question | Answer |
|---|---|
| What is AgentGuard | A standalone Intelligent Contract primitive: the adjudication and escrow-coordination layer for agent-to-agent commerce. No frontend, no backend, no operator. |
| What does it decide | Whether an agreement's acceptance criteria were met by the delivered evidence, whose fault any shortfall was, and what split of the escrow that supports. |
| Why GenLayer must decide it | The criteria are natural language and the evidence is fetched from the live web. A deterministic escrow cannot tell a dataset from an empty placeholder, a reasonable variation from a substitution, or a genuine upstream outage from a seller's own failure. One model behind one marketplace backend is an authority the losing agent cannot challenge and a second marketplace cannot reuse. |
| What evidence it uses | Only items committed to this agreement, from the per-category prefixes both agents froze at assent. Every node verifies the hash before reading a byte. An agent's own message is admissible as words and can never satisfy a criterion. |
| How consensus works | `gl.vm.run_nondet_unsafe` once per round. Each validator reproduces the round from its own fetch and model call, gates the leader's payload against its own bytes, and agrees only if every row, fact, scan, panel state and finding state matches. The payload carries no amount: validators agree on the money by construction. |
| How money moves | One payable entry (`fund_escrow`), one exit (`withdraw`, a pull-payment ledger cleared before the transfer), and eight settlement paths between them - all of which must reconcile to the escrow exactly or revert. |
| What tests prove it works | 317 Direct Mode tests on the official `genlayer-test` runner, covering all 30 brief attacks twice over (the real commerce path and the on-chain test engine), forged leaders through the captured validator closure, hostile model output, settlement bounds and the appeal lifecycle; a mutation sweep; `genvm-lint check`; preflight. See "Verified". |

## What it is

- **Identity is the signer.** An agent IS its wallet. Nobody can act as, or be judged as, someone else.
- **The agreement is frozen at assent.** `accept_agreement` hashes the criteria, weights, sources, windows, price and policy version into `terms_hash`. Nothing said afterwards adds a requirement or removes one, and the panel is told so.
- **Both agents pin the sources.** Per category, up to four https prefixes. Anything else is not fetched and not counted.
- **Hash-bound evidence.** The bytes are verified before anything reads them; changed bytes are `HASH_MISMATCH` and hold the escrow rather than settling on them.
- **Code decides the facts.** Integer facts from structured documents; duplicates, cross-agreement reuse, evidence about another job, injection phrases, hidden text and styling, staleness, deadlines.
- **Consensus decides the reading.** Whether each criterion is met, whether a deliverable is unusable, whether a difference is a variation or a substitution, whether a failure was the buyer's, the seller's or a third party's, and whether text is addressed to the panel.
- **Code derives every amount.** Level, verdict, fault, basis points, payment and refund - integer arithmetic over the policy both agents bound themselves to.
- **Every state has an exit.** A silent counterparty can never strand an escrow: `claim_stalled_agreement` is permissionless and purely wall-clock, and its four routes are documented in advance.
- **Appeals preserve history.** A readjudication is a new record naming what changed; the appealed one is never modified, and the escrow has not moved at either point.
- **An on-chain adversarial-test engine.** Register attacks and controls against a policy version; anyone runs them through the real pipeline; a rule change is checked by replaying them onto the new version before any agreement binds it.

## How it works

### For a buyer agent

1. `register_agent(capabilities_json)` from the wallet that will trade.
2. `propose_agreement(seller_wallet, terms_json)` - the service, the criteria and their weights, the evidence sources, the windows, the price.
3. `fund_escrow(agreement_id)` with exactly `price_atto` once the seller accepts.
4. `accept_delivery(agreement_id)` to pay in full, or `open_dispute(agreement_id, claim, evidence_ids)` inside the dispute window.
5. `withdraw()` for whatever the settlement credited.

### For a seller agent

1. `register_agent(capabilities_json)`, then `accept_agreement(agreement_id)` - read the criteria first; they are the whole standard.
2. Publish each evidence item at a stable https location under the agreed prefixes, then `submit_evidence(...)` with its sha256.
3. `submit_delivery(agreement_id, evidence_ids, statement)`.
4. If disputed: `submit_counterclaim`, and anyone may call `request_adjudication`.
5. `submit_appeal` within the appeal window with new evidence of your own, then `request_readjudication`.

### For anyone

`request_adjudication`, `request_readjudication`, `finalize_settlement` and `claim_stalled_agreement` are permissionless. An agent whose counterparty went quiet is never stuck waiting for them.

## Verdicts

| Verdict | Meaning | Seller's share | Escrow |
|---|---|---|---|
| `FULFILLED` | level at or above the policy's full threshold | 10000 bps | settles |
| `PARTIALLY_FULFILLED` | level at or above the partial threshold | interpolated from the policy floor | settles |
| `NOT_FULFILLED` | below the partial threshold, or a substituted service | `not_fulfilled_seller_bps` | settles |
| `BUYER_NON_COOPERATION` | the buyer withheld what the work needed | `buyer_non_cooperation_seller_bps` | settles |
| `MUTUAL_FAULT` | the buyer withheld input and the seller changed scope | `mutual_fault_seller_bps` | settles |
| `EXTERNAL_DEPENDENCY_FAILURE` | a declared dependency failed outside both agents' control | `external_failure_seller_bps` | settles |
| `SELLER_NON_PERFORMANCE` | funded, nothing delivered by the deadline (the stalled route) | 0 | refund in full |
| `REJECTED` | the buyer went silent under a policy where silence is not acceptance | 0 | refund in full |
| `INSUFFICIENT_EVIDENCE` | too little usable evidence, or too much weight unverifiable | 0 | **held** |
| `CONFLICTING_EVIDENCE` | fabrication, or text aimed at the panel | 0 | **held** |
| `SOURCE_UNAVAILABLE` | an allowed item unreachable, or its bytes changed | 0 | **held** |
| `INCONCLUSIVE` | a malformed item, an unusable model answer, or a question undecided whose answer could have changed the verdict | 0 | **held** |

A held escrow is not a lost one: the agreement stays open for an appeal, and the stalled-agreement route returns it to the agent who paid it once the windows pass.

## The split

Integer arithmetic in `_seller_bps` and `_split`; full rules in [`docs/settlement.md`](docs/settlement.md).

```text
level        = satisfied_weight * 100 // total_weight      (OPTIONAL criteria are never scored)
seller_bps   = 10000                                        if FULFILLED
             = min(10000, floor + (10000 - floor) * (level - partial) // (full - partial))
             = the policy's share                           for each fault verdict
seller_atto  = escrow * seller_bps // 10000
buyer_atto   = escrow - seller_atto                         (the remainder is the buyer's)
```

## Lifecycle

```text
propose_agreement --> PROPOSED --accept_agreement--> ACCEPTED --fund_escrow--> FUNDED
      (buyer)            |         (seller, frozen)     |        (buyer, GEN)     |
                     cancel                          cancel                submit_delivery
                         v                              v                         v
                     CANCELLED                      CANCELLED                 DELIVERED
                                                                             /         \
                                                          accept_delivery   /           \  open_dispute
                                                                           v             v
                                                                      FINALIZED       DISPUTED
                                                                     (paid in full)      |
                                                                                request_adjudication
                                                                                         v
                                                                                   ADJUDICATED
                                                                                    /        \
                                                        submit_appeal + request_readjudication \
                                                                   (new record, same escrow)    \
                                                                                                 v
                                                                        finalize_settlement --> FINALIZED
                                                                        claim_stalled_agreement -^
                                                                                                 |
                                                                                            withdraw()
```

## Contract

`contracts/agentguard.py`, runner `py-genlayer:1jb45aa8...` (pinned), 22 writes, 18 views.

### Write methods

| Method | Who | Does |
|---|---|---|
| `register_agent(capabilities_json)` | the wallet itself | one profile per wallet |
| `register_policy(policy_json)` | anyone (becomes owner) | version 1 of a settlement policy |
| `publish_policy_version(policy_id, policy_json)` | owner | a successor; the previous version is SUPERSEDED |
| `revoke_policy_version(policy_id, version)` | owner | terminal; live agreements keep what they froze |
| `propose_agreement(seller_wallet, terms_json)` | buyer | `AG-nnnnnn` |
| `accept_agreement(agreement_id)` | seller | freezes and hashes everything |
| `cancel_agreement(agreement_id)` | either | only before the escrow |
| `fund_escrow(agreement_id)` **payable** | buyer | exactly `price_atto` |
| `submit_evidence(agreement_id, category, url, sha256, issuer, description)` | either | `EV-nnnnnn`; nothing is fetched yet |
| `submit_delivery(agreement_id, evidence_ids, statement)` | seller | the delivery and its statement |
| `accept_delivery(agreement_id)` | buyer | settles in full, no consensus round |
| `open_dispute(agreement_id, claim, evidence_ids)` | buyer | inside the dispute window |
| `submit_counterclaim(agreement_id, statement, evidence_ids)` | seller | once |
| `request_adjudication(agreement_id)` | anyone | the consensus round; no money moves |
| `submit_appeal(agreement_id, reason, new_evidence_ids)` | either | inside the appeal window, own new evidence |
| `request_readjudication(appeal_id)` | anyone | the consensus round; a new record |
| `finalize_settlement(agreement_id)` | anyone | after the window, if the verdict settles |
| `claim_stalled_agreement(agreement_id)` | anyone | the wall-clock exit, four documented routes |
| `withdraw()` | anyone owed | pull payment; the ledger is cleared first |
| `register_adversarial_case(...)` | policy owner | a case bound to a policy version |
| `run_adversarial_case(case_id)` | anyone | the consensus round; records pass or fail |
| `replay_adversarial_case(case_id, target_version)` | policy owner | the case onto another version |

### Read methods

`get_config`, `health_check`, `get_agent`, `get_policy`, `get_agreement`, `get_evidence`, `get_delivery`, `get_dispute`, `get_adjudication`, `get_latest_adjudication`, `get_appeal`, `settlement_status`, `get_claimable`, `get_agreement_history` (paged), `list_agent_agreements` (paged), `get_adversarial_case`, `list_adversarial_cases` (paged), `get_stats`. Views never revert on unknown ids and read bounded slices only. [`docs/integration.md`](docs/integration.md) has the shapes.

## Verified

| Check | Command | Result |
|---|---|---|
| Direct Mode | `python -m pytest tests/direct -q` | 317 passed |
| Preflight | `python scripts/preflight.py` | 47 checks, 0 failed |
| GenVM validation | `genvm-lint check contracts/agentguard.py --json` | ok, 40 methods, 0 errors (I200 informational) |
| Lint | `ruff check .` | clean |
| Mutation sweep | `python scripts/mutation_check.py --jobs 3` | 190 mutations, 190 killed, 0 survived, with an accept-control; 11 equivalent mutants named with their reasons in the script (`deploy/mutation_sweep_885c7fa.txt`) |
| Sample adjudication | `python scripts/run_direct_mode.py` | FULFILLED, 100/100, seller 400.00 GEN |
| Integration (the deployment) | `python -m pytest tests/integration -q` | 6 passed, 1 skipped (the opt-in live write) against `0xD67E15e7`; the superseded record passed 7 including the write |
| Live run (the deployment) | `python scripts/live_scenarios.py <address> --raw-base ... --only A,C` | 54 transactions, every asserted check held, both judge-round fixes shown on chain ([`docs/judge-round.md`](docs/judge-round.md)); the 26-case suite and the arc below ran on the superseded record `0x972AdCD7` |

### On StudioNet, with real GEN

The judge-round live run on `0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c` is written up in [`docs/judge-round.md`](docs/judge-round.md). What follows is the live run on the superseded record `0x972AdCD7`, which exercised the same code apart from the two changes that round made.

Everything below is in `deploy/live_scenarios_transcript.json`, with every
transaction hash, leader result and validator vote.

- **The commerce arc.** The buyer escrowed 0.05 GEN
  ([fund](https://explorer-studio.genlayer.com/tx/0x83ffdcd42f35033439d287ec7e600961958f44e77ef063f56f5d433e8164c4ae)).
  The seller's first delivery was a run log and a receipt, and the first round
  held the escrow as INSUFFICIENT_EVIDENCE: a log cannot show 5,000 delivered
  rows, and too much weight was unverifiable. The seller appealed with the
  summary and the method report, and the readjudication found every scored
  criterion met, 100/100
  ([readjudicate](https://explorer-studio.genlayer.com/tx/0xbe7d487f670a392ebe2a599f2455d0fc9653f785dc4c797c51d5839d7d889e26)).
  An early finalization was refused; after the appeal window the agreement
  settled
  ([finalize](https://explorer-studio.genlayer.com/tx/0xf751c581bad609a6ddb7985629f8997e1cb9c1c5be3a185c16b508080445a9cb)),
  and the seller's wallet balance rose by exactly 0.05 GEN when it withdrew
  ([withdraw](https://explorer-studio.genlayer.com/tx/0x88490959b8aecf26a83d8bb70133e985e00f05197b07355bdc06c0801ebdc254)).
  A second withdrawal was refused.
- **The adversarial suite.** All 26 on-chain cases ran through the engine and
  held: 25 decided by the panel, one by code. A17 held on its second run. Its
  first run's agreement marked no criterion as needing the buyer's input, and
  the panel's note said so exactly - "The agreement does not require buyer
  input, so this indicator is not established." The case now records that
  obligation in its terms; both runs are in the transcript.
- **The other exits.** A buyer that accepted paid in full with no consensus
  round
  ([accept](https://explorer-studio.genlayer.com/tx/0x976ed5de840e998031be6411846a0f51112a01603060e0e83091566de2be7783)),
  and a funded agreement that was never delivered returned the escrow to the
  buyer once its windows passed
  ([claim](https://explorer-studio.genlayer.com/tx/0xd4e932a3be812bde63883ad9c3cdecd9b9d67f75a995d9df418eae83d3e269b8)).
  Both withdrawals moved exactly 0.05 GEN on chain, and 13 refusals held.
- **Consensus.** 3 of 32 rounds stored nothing and were asked again (A08, A16
  and A17's second run); the deployment this one superseded needed 11 of 38.

## Repository

```text
contracts/agentguard.py         the contract
tests/direct/                   Direct Mode suite (eight modules)
tests/integration/              StudioNet checks against the canonical deployment
fixtures/                       evidence documents, demo wallets, the case catalogue
scripts/generate_fixtures.py    regenerates fixtures/ byte for byte
scripts/run_direct_mode.py      one readable sample adjudication
scripts/preflight.py            repository invariants
scripts/mutation_check.py       mutation kill sweep with an accept-control
scripts/deploy_studionet.py     deploy and verify source parity
scripts/inspect_deployment.py   read-only inspection of a deployment
scripts/diagnostic_rounds.py    disposable rounds that show why validators split
scripts/live_scenarios.py       the live run on StudioNet, with real GEN
docs/                           architecture, threat model, agreement, evidence, settlement, consensus, integration, deployment
```

## Getting started

```bash
python -m pip install -r requirements-test.txt
```

```bash
python scripts/fetch_genvm_bundle.py
```

```bash
python -m pytest tests/direct -q
```

```bash
python scripts/run_direct_mode.py
```

`fetch_genvm_bundle.py` seeds the GenVM runner bundle that `genlayer-test` 0.29.2 cannot fetch on a cold cache. No key or network account is needed for anything above; [`docs/deployment.md`](docs/deployment.md) covers StudioNet.

## Security

Everything retrieved is untrusted data: code scans for instruction phrases, hidden characters and hiding styles before any model is asked, the prompt frames every item and label as the submitting agent's claim, and no model produces an amount. [`docs/threat-model.md`](docs/threat-model.md) walks all thirty brief attacks with their capability, input, safe behaviour, verdict, payment bounds and test.

## Limitations

- A hash proves the bytes have not changed since commitment, not that the issuer is genuine; provenance rests on the prefixes the two agents froze.
- `minimum_evidence_items` counts items, not independent publishers; independence comes from criteria that name different categories.
- Everything committed is public on-chain. This is not for confidential deliverables; commit a hash of the artifact and serve it where only the parties can read it, and the panel will say so.
- Panel findings depend on validator models. They are grounded and compared strictly, and a round that splits produces no verdict and holds the escrow - which costs the honest party time.
- Views take the caller's clock (`as_of`); a view has no clock of its own.
- The contract adjudicates between the two parties to one agreement. Two agents that collude against a third party are outside its scope.

## Not production-ready

No audit. The demo policy, the demo agents and every evidence document are fixtures in this repository. StudioNet is a test network, and the escrow is test GEN. AgentGuard does not eliminate fraud, guarantee service quality, or replace a legal agreement between the parties' operators.

## Licence

MIT - see [LICENSE](LICENSE).
