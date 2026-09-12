# Deployment

## The deployment of record

`deploy/deployment.json` is the machine-readable record: address, deploy
transaction, validator votes, the source commit and blob, both sha256 hashes
and `byte_identical`. The table below is filled from it at release, and
`python scripts/deploy_studionet.py --verify` re-checks it at any time.

| Item | Value |
|---|---|
| Contract | `0xF8bC4Da696306CF5874560469c8483793EC132Ff` |
| Explorer | https://explorer-studio.genlayer.com/address/0xF8bC4Da696306CF5874560469c8483793EC132Ff (the Code tab shows the deployed source) |
| Deploy transaction | `0x5650702a29afdcf9c8d1c97aa8c0f3914dde4acadffce85ee6d8174fb25e161b` |
| Status | `FINALIZED`, leader execution `SUCCESS`, validator votes `AGREE` x3, `IDLE` x2 |
| Source | `contracts/agentguard.py` at commit `32f5ac0`, blob `43acf32`, sha256 `6233466b...a491` |
| Source parity | the source read back with `gen_getContractCode` has the same sha256 (`python scripts/deploy_studionet.py --verify`) |
| Signer | `0xDe156e827E6a6D65Da58f06EaeEbA2A57BC57E8c` |

Addresses that are **not** the deployment of record - disposable diagnostic
deployments under `deploy/diagnostics/`, and any superseded canonical
deployment - are listed in the same file under `other_addresses`, each with
the reason it was superseded.

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
