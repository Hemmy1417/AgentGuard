# Submission

**Category** - agent-to-agent commerce: adjudication and escrow coordination.

**Title** - AgentGuard: Adjudicated Trust for AI Agent-to-Agent Commerce.

**One-line thesis** - two AI agents escrow a price against an agreement whose
acceptance criteria are frozen and hashed at assent; when they disagree, one
consensus round reads hash-bound evidence from sources they both pinned, and
the contract's own arithmetic turns the agreed findings into a split of the
escrow.

**Repository** - https://github.com/Hemmy1417/AgentGuard

**Canonical StudioNet address** - `0x972AdCD7e9ac0D93FD8D678c9fF59cf5B714b4c2`

**Explorer URL** - https://explorer-studio.genlayer.com/address/0x972AdCD7e9ac0D93FD8D678c9fF59cf5B714b4c2
(the Code tab shows the deployed source).

**Deployment tx** - `0xe77a7f25ad51b29beafde1320b8c717014d29990eb3f9b43fd6f58d8d6c4b266`, FINALIZED, leader execution SUCCESS.

**Deployment source** - `contracts/agentguard.py` at commit `e2853c7`,
sha256 `c1a3580dd2583e7ed01ef7929ed9332b62086e07fdd9a20893f8155b79a5b4c7`; the source read back with `gen_getContractCode` has the same
sha256 (`python scripts/deploy_studionet.py --verify`).

## Why GenLayer is required

The settlement depends on whether natural-language acceptance criteria were
met by evidence fetched from the live web. A deterministic escrow cannot tell
a delivered dataset from an empty placeholder, a reasonable variation from a
substitution, or a genuine upstream outage from a seller's own failure. One
model behind one marketplace backend can - but it is an authority the losing
agent cannot challenge, a second marketplace cannot reuse, and nobody can
audit. GenLayer makes the reading itself the thing that is agreed: several
validators each fetch the bytes, hash-verify them, ask their own model, and
ratify only if the structured findings match.

## Consensus mechanism

`gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`, once per adjudication,
readjudication or adversarial case. Every validator reproduces the round from
its own fetches and its own model call, then gates the leader's payload
against its own verified bytes: exact key set, known enums, code-decided
fields recomputed, every quote's words re-grounded in the bytes that validator
hashed itself. It then compares row statuses and byte counts, structured
facts, the agreement link and the injection and hidden-text scans, the panel
state and reason, and the state and deciding layer of every criterion and
indicator - except that for the one indicator that records fault and never
moves money, only whether it is PRESENT. Notes and quote choice are never
compared: they differ between models and decide nothing. The equivalence rule
is stored in the contract and returned by `get_config`.

## Deterministic responsibilities

Identity (each agent is its signing wallet); the agreement, its criteria,
weights and windows, hashed at assent; the per-category source allowlist;
sha256 verification before anything reads a byte; every number read from
structured documents; duplicates, cross-agreement reuse, staleness, deadlines,
injection markers, hidden text; the fulfillment level; the verdict; both fault
levels; the seller's basis points; the payment and the refund; escrow
conservation; the pull-payment ledger; every state transition.

## Failure policy

Fail closed, and hold rather than guess. An unreachable or changed source, an
oversized or malformed item, an unusable model answer, too little usable
evidence, fabrication or text aimed at the panel, or an undecided question
whose answer could have changed the verdict produces a verdict that pays nobody
and leaves the escrow in place. A held escrow is never stranded: every state
that can hold funds has a permissionless wall-clock exit
(`claim_stalled_agreement`) whose four routes are decided in advance, and an
escrow never shown to be earned returns to the agent who paid it. Money moves
in exactly two places - `fund_escrow` in, `withdraw` out - and `_settle`
reverts unless the two allocations reconcile to the escrow exactly.

## Reuse surface

`settlement_status(agreement_id, as_of)` answers everything a downstream
contract needs in one read: status, verdict, level, both fault levels, the
allocation, whether it settles, whether the appeal window is open, whether it
can be finalized or claimed now. `get_adjudication` / `get_latest_adjudication`
return the full immutable record with receipts, findings and reason codes;
`get_claimable(wallet)` is the ledger; `get_config` publishes every enum,
bound and the equivalence rule. `docs/integration.md` has the shapes and the
five things a caller must get right.

## Test results

| Check | Command | Result |
|---|---|---|
| Direct Mode | `python -m pytest tests/direct -q` | 313 passed |
| Preflight | `python scripts/preflight.py` | 47 checks, 0 failed |
| GenVM validation | `genvm-lint check contracts/agentguard.py --json` | ok, 40 methods, 0 errors |
| Lint | `ruff check .` | clean |
| Mutation sweep | `python scripts/mutation_check.py --jobs 3` | recorded in `deploy/` |
| Sample adjudication | `python scripts/run_direct_mode.py` | FULFILLED, 100/100, seller 400.00 GEN |
| Integration | `AGENTGUARD_LIVE_WRITES=1 pytest tests/integration -v` | recorded below |
| Live run | `python scripts/live_scenarios.py <address> --raw-base ...` | recorded below |

## Live evidence

`deploy/live_scenarios_transcript.json` holds every transaction hash, leader
execution result and validator vote from the live run, together with what was
asserted and what was recorded. The run covers the commerce arc with real GEN
(agreement, escrow, delivery, dispute, adjudication, appeal, readjudication,
finalization, withdrawal), the adversarial catalogue through the on-chain test
engine, the buyer-acceptance and stalled-refund exits, and the refusals.

## Limitations

A hash proves the bytes have not changed since commitment, not that the issuer
is genuine. Panel findings depend on validator models: they are grounded and
compared strictly, and a round that splits produces no verdict and holds the
escrow, which costs the honest agent time. Everything committed is public
on-chain. The contract adjudicates between the two parties to one agreement;
collusion against a third party is out of scope. No audit; the demo policy,
agents and evidence are fixtures in this repository; StudioNet is a test
network. AgentGuard does not eliminate fraud, guarantee service quality, or
replace a legal agreement between the parties' operators.

## Reviewer fast path

```bash
python -m pip install -r requirements-test.txt && python scripts/fetch_genvm_bundle.py
```

```bash
python scripts/run_direct_mode.py
```

```bash
python -m pytest tests/direct -q
```

```bash
python scripts/deploy_studionet.py --verify
```

Then read, in order: `docs/architecture.md` (the boundary between code and
consensus), `docs/settlement.md` (how a verdict becomes wei), and
`docs/threat-model.md` (all thirty attacks with their tests). The contract is
one file, `contracts/agentguard.py`.

## Portal description (986 characters)

AgentGuard is a standalone GenLayer Intelligent Contract that holds the escrow
between two AI agents and settles it from an adjudication of the agreement
they assented to. The criteria, weights, evidence sources and windows are
frozen and hashed at assent. On a dispute, validators independently fetch and
sha256-verify every evidence item, read every number from structured documents
in code, and answer only what needs reading - each finding carrying quotes
every validator re-grounds in its own bytes. Code then derives the fulfillment
level, the verdict, both fault levels and the split, so no model output reaches
an amount. It exposes settlement_status, get_adjudication and get_claimable for
downstream contracts, and every state has a permissionless wall-clock exit.
Verified with 313 Direct Mode tests on the official genlayer-test runner, GenVM
lint and SDK validation, a mutation sweep with an accept-control, StudioNet
integration tests and a FINALIZED StudioNet deployment.
