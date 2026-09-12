# Decision record

Why AgentGuard, why this shape, and why it is a standalone Intelligent
Contract.

## The question it answers

> Given the agreement these two AI agents assented to, and only evidence from
> the sources they froze at assent, was the service fulfilled - and what split
> of the escrow does that support?

## Delete-GenLayer test

Remove consensus and one of two things is left. Either the marketplace's own
backend reads the delivery with one model and decides alone - and the agent
that loses cannot challenge a reading nobody else performed, nor can a second
marketplace reuse the result without trusting the first. Or a deterministic
escrow releases on a signature or a timer, which cannot tell a delivered
dataset from an empty placeholder, a reasonable variation from a substitution,
or a genuine upstream outage from a seller's own failure. What breaks is
exactly the part that needs reading: whether the work meets criteria written
in natural language, whose fault a failure was, and whether the evidence is
what it claims to be.

AgentGuard has independent validators each fetch, hash-verify and read the
same bytes, answer the same partitioned questions, and agree finding by
finding - and it keeps every amount in code. The panel never sees a number it
could move; `_derive`, `_seller_bps` and `_split` turn agreed findings into
wei, and `_settle` refuses anything that does not reconcile to the escrow
exactly.

## Portfolio collision analysis

Earlier builds by the same author that touch agent commerce or escrow, and how
AgentGuard differs:

| Build | What it decides | Overlap | Why AgentGuard is not a copy |
|---|---|---|---|
| Verity | whether an agent's work claim is verified, then settles | agent work, settlement | Verity verifies **one** agent's claim against sources it names, and its lesson - require consensus on what has a consequence, and only that - is the spine here. AgentGuard adjudicates **between two** agents under an agreement both assented to: frozen criteria with weights, a fulfillment level, fault attributed to buyer, seller or a third party, a partial split, appeals, and four terminal exits. |
| Aegis | freelance escrow, human parties, milestone release | escrow, dispute | Aegis releases a milestone on a judgment about a human's work. AgentGuard's parties are wallets with no human in the loop, so every input is machine-produced evidence with a hash, the criteria are frozen at assent rather than argued afterwards, and no path waits for a person to click. |
| GroundTruth | milestone escrow with evidence | escrow, evidence | GroundTruth asks whether a milestone was met. AgentGuard asks how much of an agreement was met, on a weighted level, and who caused the shortfall - and it maps that to a split the two agents agreed in advance, not to a yes/no release. |
| Adjudex | adjudication of a dispute over chain-anchored evidence | adjudication, evidence binding | Adjudex is a general dispute court; AgentGuard is one market's court, with an escrow it holds and a settlement policy the parties bind at assent. The S34 floor and chain-anchored evidence lessons carry over. |
| Kredo | undercollateralized lending scored by an AI | none but "money and a model" | Kredo prices risk. AgentGuard prices nothing; it allocates money already escrowed against a standard already agreed. |
| InsureShield, CredenceLend | whether committed documents satisfy a policy; adversarial evidence handling | hash-bound evidence, code facts plus a panel, the adversarial-test engine | The closest ancestry, and the reason the evidence model is trusted. Both decide about **one** party's documents. AgentGuard adds two parties with opposed interests, an escrow with real value, fault attribution, partial settlement arithmetic, and a party-interest rule on quotes that neither ancestor needed. |
| AgentShield, Retinue, Gauntlet | agent guardrails, mandate supervision, injection arena | prompt-injection defence | Those decide whether an agent behaved. AgentGuard decides whether a service was delivered, and treats injection as one indicator among several rather than the subject. |

Reused deliberately, from builds that shipped and were reviewed: the pinned
StudioNet runner, hash verification before any read, "the model returns
findings, code derives the outcome", word-level quote grounding, the structural
gate re-run by every validator and again on the ratified payload, the
commitment-ordered registry, the pull-payment ledger, and the on-chain
adversarial-test engine. Those parts are not new and are not presented as new;
what is new is the two-party commerce spine on top of them.

## Ecosystem collision analysis

| Existing thing | What it does | Why it is not this |
|---|---|---|
| x402 and agent payment rails | let one agent pay another per request | they move money; they have no notion of whether the service was delivered |
| Escrow smart contracts (deterministic) | hold funds until a signature, an oracle or a timer | cannot read a deliverable, so a dispute ends in a human, a multisig or a forfeit |
| Reputation and staking markets | punish a bad counterparty afterwards | they price the risk of a dispute; they do not resolve one |
| Optimistic dispute games (Kleros-style) | crowd-judge a dispute with staked jurors | human jurors, hours to days, and the evidence is whatever a party pastes; here the panel is validators, the evidence is hash-bound to sources frozen at assent, and the settlement is one transaction |
| LLM-as-judge in a marketplace backend | reads the delivery and decides | one operator, one model, no record either side can check, and nothing stops the operator |

## Candidates considered

| # | Candidate | Score /5 | Verdict |
|---:|---|---:|---|
| 1 | **Agent-to-agent commerce adjudication and escrow** | 5 | **selected** - the decision is unavoidably a reading, the money is on-chain, and both parties are adversarial |
| 2 | Agent capability attestation (does this agent do what it claims?) | 3 | a claim about the future, not about evidence; reduces to reputation |
| 3 | Agent output quality scoring service | 2 | no counterparty, no money, no dispute: an API, not a contract |
| 4 | Multi-agent task marketplace with matching | 2 | matching and pricing are deterministic; only the dispute needs consensus - which is candidate 1 |
| 5 | Agent-to-agent SLA monitoring | 3 | mostly deterministic metrics; the interesting part (was the breach the provider's fault) is a subset of candidate 1 |

Rejected because they either need no consensus (3, 4), or collapse into the
selected primitive once the part that needs consensus is isolated (2, 5).

## Three consumers

1. **An agent marketplace** escrows every job through AgentGuard and reads
   `settlement_status` to release the buyer's downstream obligation; it gets a
   dispute path it does not have to operate or defend.
2. **An autonomous buyer agent** (a data pipeline that buys enrichment) funds
   an agreement per job and needs no human when a delivery is short: it
   disputes, and the split is computed from criteria it agreed to in advance.
3. **A seller agent** offering a service to strangers takes work it would
   otherwise refuse, because a buyer cannot simply withhold payment: the
   adjudication is permissionless, and a silent buyer loses the escrow to the
   policy's silence rule.

## Hardest technical risk

Validator model diversity. StudioNet validators span several model families,
and a format-strict or overlapping question splits them - a lesson from an
earlier build where every round disagreed because two models filed the same
fact under different indicators. The mitigations here are structural: each
question has exactly one home, the prompt partitions them explicitly, quotes
are matched at word level rather than by string equality, notes and quote
choice are never compared, and a round that still splits produces no verdict
and holds the escrow rather than settling on a coin flip. `deploy/diagnostics/`
records disposable rounds run before the canonical deployment for exactly this.

The second risk is that money and meaning meet. It is handled by keeping them
apart: no code path leads from model output to a transfer, the payload has no
amount field, `_settle` reverts unless the two allocations reconcile to the
escrow exactly, and the ledger is cleared before any transfer is emitted.

---

- **Repository:** https://github.com/Hemmy1417/AgentGuard
- **Category:** agent-to-agent commerce - adjudication and escrow coordination
- **Why GenLayer is load-bearing:** the settlement depends on whether
  natural-language acceptance criteria were met by evidence fetched from the
  live web, verified independently by each validator and agreed finding by
  finding. No deterministic contract can decide that, and no single model
  should be trusted to.
