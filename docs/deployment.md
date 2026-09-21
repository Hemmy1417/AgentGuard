# Deployment

## The deployment of record

`deploy/deployment.json` is the machine-readable record: address, deploy
transaction, validator votes, the source commit and blob, both sha256 hashes
and `byte_identical`. The table below is filled from it at release, and
`python scripts/deploy_studionet.py --verify` re-checks it at any time.

| Item | Value |
|---|---|
| Contract | `0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c` |
| Explorer | https://explorer-studio.genlayer.com/address/0xD67E15e75F434f7265a31eEf5dA47c6966ecF33c (the Code tab shows the deployed source) |
| Deploy transaction | `0xb362ac3098883e51d43faabf8239dae2ff501a91b5596232f470912135761762` |
| Status | `FINALIZED`, leader execution `SUCCESS`, validator votes `AGREE, AGREE, IDLE, AGREE, IDLE` |
| Source | `contracts/agentguard.py` at commit `c5dd0c4`, blob `b8863c6`, sha256 `cedeff5f...ffde` |
| Source parity | the source read back with `gen_getContractCode` has the same sha256 (`python scripts/deploy_studionet.py --verify`) |
| Signer | `0xDe156e827E6a6D65Da58f06EaeEbA2A57BC57E8c` |

It replaced `0x972AdCD7e9ac0D93FD8D678c9fF59cf5B714b4c2` after the judge round of 21
September 2026 ([`judge-round.md`](judge-round.md)). Addresses that are **not** the deployment of record are listed in the same
file under `other_addresses`, with the reason. Read on 12 September 2026,
every one of them reports `escrow_held_atto` 0 and `claimable_atto` 0 from
`health_check`: nothing is held and nothing is owed. (The superseded record `0x972AdCD7` also reads 0 and 0, but its chain balance is
49999999999999999 atto kept by StudioNet from a refused funding - see
[`judge-round.md`](judge-round.md#one-further-finding-recorded-and-not-changed-here).)

- Five **diagnostic** deployments (`deploy/diagnostics/`): disposable
  addresses used to see what real validators do with the panel-decided cases
  before a canonical deployment.
- `0xF8bC4Da696306CF5874560469c8483793EC132Ff`, **superseded**: the live run's
  own agreement terms set a 60-second appeal window - shorter than the two
  transactions an appeal takes on StudioNet - so the contract refused the
  appeal exactly as written. That agreement was then closed through the
  documented stalled route (`UNSETTLED_ADJUDICATION`: the buyer refunded in
  full and withdrawn), so the address holds no escrow. The script now gives the
  arc a ten-minute appeal window.
- `0xE8c834475F23447299835fD14721dBCA72f5c7F2`, **superseded**: an interrupted
  attempt had already consumed the agreement id `AG-000001`, and the fixture
  evidence names that id inside its own contents, so the arc was restarted from
  a clean deployment rather than run against evidence the contract would
  correctly flag as belonging to another agreement.
- `0xF6705A905c766E51945535349322fEE25C075E45`, **superseded**: this one ran
  the arc far enough to find a real fault. Its readjudication came back
  INCONCLUSIVE with every criterion SATISFIED at 100/100, because the panel had
  left `BUYER_CRITERIA_CHANGE` undecided - a question that records fault and
  can never move money. The contract now holds an escrow only for a question
  whose answer could have changed the verdict (`OUTCOME_INDICATORS`), which is
  what the deployment of record carries. That agreement's escrow was returned
  to the buyer through the stalled route and withdrawn (a balance change of
  0.05 GEN, observed), so the address holds nothing.
- `0xbB846F3Cc63e0C8fCF138B9CF0e407202158c861`, **superseded**: the deployment
  of record until its own live run showed validators losing quotes they had
  copied exactly. Its quote grounding read every line break as an elision, so a
  verbatim quote of a paragraph whose last line was one word was refused, and
  it cut an over-long quote once, so a cut that stranded one word after a line
  break lost a quote that grounded as written. Neither could ground anything
  false; both put validators in disagreement for no reason the evidence gave
  (`docs/consensus.md`, quote grounding, has the rounds). Its run is kept in
  `deploy/superseded/live_scenarios_0xbB846F3C.json`: the whole commerce arc
  with real GEN - a first round of INSUFFICIENT_EVIDENCE, the appeal, a
  readjudication of FULFILLED, and 0.05 GEN finalized and withdrawn to the
  seller's wallet - and all 26 on-chain cases, of which 23 held and A03, A12
  and A16 did not. Phase C was not run there.

## Network and assumptions

| Item | Value |
|---|---|
| Network | GenLayer StudioNet, chain id 61999 |
| RPC | `https://studio.genlayer.com/api` |
| Explorer | `https://explorer-studio.genlayer.com` (`/address/<address>` has a Code tab with the deployed source; `/tx/<hash>`) |
| Runner | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`, pinned in the contract header |
| Gas | StudioNet is gasless; a signer needs no funds to write |
| Value | escrow is real GEN. The live run funds the buyer wallet from the StudioNet faucet (`client.fund_account`) and escrows 0.05 GEN per agreement |
| Rate limits | per IP: 60 requests a minute, 1000 an hour. `scripts/studionet_transport.py` retries transport failures and rate-limit answers only - never a contract revert |

The blank line after the `Depends` comment in the contract header is
load-bearing: GenVM reads the leading contiguous comment block for the runner
metadata, and prose glued onto it turns a deploy into `invalid_contract` with
empty stderr.

## Keys and environment

No private key is read from the environment and none is committed.

| File (gitignored) | Created by | Holds |
|---|---|---|
| `.data/deployer.json` | `scripts/deploy_studionet.py` on first run | the deployer key |
| `.data/demo_wallets.json` | `scripts/generate_fixtures.py` when `fixtures/wallets.json` does not exist | the six demo agent keys; their public addresses are in `fixtures/wallets.json` |

`.env.example` lists the only two optional settings
(`AGENTGUARD_LIVE_WRITES`, `GENVM_VERSION`), both empty.

## Build

There is no build step: GenVM runs the Python source. The gates before a
canonical deployment are:

```bash
python scripts/preflight.py
```

```bash
python -m pytest tests/direct -q
```

```bash
genvm-lint check contracts/agentguard.py --json
```

```bash
python scripts/mutation_check.py --jobs 3
```

## Deploy

The contract must be committed and unmodified; the script refuses otherwise,
so the deployment corresponds to an identifiable commit.

```bash
python scripts/deploy_studionet.py
```

It signs with `.data/deployer.json`, waits for `FINALIZED`, requires the
leader's execution result to be `SUCCESS` (lifecycle status alone is not
execution success), reads the deployed source back with `gen_getContractCode`,
compares its sha256 with the committed file, and writes
`deploy/deployment.json`.

Before the canonical deployment, the panel-decided cases are worth running on
a **disposable** address first: StudioNet validators span several model
families, and a round that splits them explains itself in the nodes' stdout.

```bash
python scripts/diagnostic_rounds.py https://raw.githubusercontent.com/<owner>/<repo>/<commit>/fixtures/
```

Those runs are kept under `deploy/diagnostics/` and are never deployments of
record.

## After deployment

Source parity, schema, health and version, read-only and keyless:

```bash
python scripts/deploy_studionet.py --verify
```

```bash
python scripts/inspect_deployment.py
```

The live run needs the fixtures served from a public https host that returns
exactly the committed bytes. Commit-pinned `raw.githubusercontent.com` URLs do
that, and the script verifies every location against the local bytes before it
sends a transaction:

```bash
python scripts/live_scenarios.py <address> --raw-base https://raw.githubusercontent.com/<owner>/<repo>/<commit>/fixtures/
```

It is resumable: every transaction hash is saved before its receipt is
awaited, so an interrupted run continues without resending anything. The
transcript is `deploy/live_scenarios_transcript.json`.

The fixture catalogue is dated. Its evidence carries fixed `as_of` timestamps
around the demo agreement's deadline (September 2026, set as constants in
`scripts/generate_fixtures.py`), and the demo policy counts an item older than
30 days as stale. A live run much later will therefore see `STALE_EVIDENCE` on
the structured items and verdicts that differ from the catalogue. Move the
dates in the generator and regenerate, or raise `maximum_evidence_age_days` in
the policy the run registers.

Inspect a stored result:

```bash
genlayer call <address> get_adjudication --args AD-000001
```

```bash
genlayer call <address> settlement_status --args AG-000001 2026-09-13T00:00:00Z
```

## Integration tests

```bash
python -m pytest tests/integration -v
```

Read-only against the recorded deployment: source parity, the public surface,
the views, and the adjudication and settlement the live run recorded. One
write goes through real consensus with `AGENTGUARD_LIVE_WRITES=1`.

## Reset and teardown

A deployed contract cannot be deleted and its records are immutable by design.
To start clean, deploy a fresh instance (a new address) and point
`deploy/deployment.json` at it, moving the previous address to
`other_addresses` with the reason. Deleting `.data/` rotates every local key;
`fixtures/wallets.json` must then be deleted too and the fixtures regenerated,
because the documents name the demo wallets.

Escrow held by a superseded deployment is not stranded: every state has a
wall-clock exit (`claim_stalled_agreement`), and whatever it credits is
withdrawable from that address forever.
