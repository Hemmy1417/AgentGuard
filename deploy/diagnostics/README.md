# Diagnostic rounds

Disposable deployments, run **before** the canonical one, to see what real
validators do with the panel-decided cases. Nothing here is a deployment of
record; the addresses are listed in `deploy/deployment.json` under
`other_addresses` so no reader mistakes one for the contract.

```bash
python scripts/diagnostic_rounds.py https://raw.githubusercontent.com/<owner>/<repo>/<commit>/fixtures/
```

Each run records, per round: the case, the observed verdict and share, whether
it held, and for every node its model, its vote and the tail of its stdout -
where the contract prints `[DISAGREE]`, `[DOWNGRADE]` and
`[MODEL_OUTPUT_INVALID]`.

## What the first run found (2026-09-12, `0xB398982d7627c573bEe090D28B89CEf807149601`)

Seven rounds across five cases. The honest baseline held twice, in 65 and 68
seconds, with every validator agreeing. Three rounds did not go as the
catalogue said they would, and all three were the catalogue's fault rather than
the panel's:

| Round | What happened | What it changed |
|---|---|---|
| A03, fabricated log | every model read a log claiming 5,250 rows processed in one second as ordinary | code now reads `elapsed_seconds` from the log's own timestamps and gives the panel both numbers, and the manipulation question points at the comparison |
| A17, withheld access | three models answered ABSENT: the delivery showed the work completed, so withholding a key had prevented nothing. One model answered PRESENT with a perfect quote, and the round split | the case was incoherent. A17 now carries a delivery that stops at authentication, so the withholding actually blocked the work; A18, where nothing was blocked, now expects the seller to be paid in full |
| A30, ambiguous criteria | the panel read the honest method report as satisfying the criterion it satisfies | correct. The case now uses a method report that states no limitation at all, so what is exploited is the criterion's wording rather than the panel's judgment |

One round (A11) ended with three validators printing `[DISAGREE] leader
payload failed the structural gate`. With identical bytes the gate is a pure
function of the payload, and the one input-dependent way it could reject a
payload the leader itself built was a note: `_clean_note` trimmed to the cap
and could leave a trailing space, which the gate - which re-cleans what it is
given and compares - then refused. The trim is now idempotent, and
`test_note_cleaning_is_idempotent` and
`test_a_long_note_does_not_break_the_round` pin it.

## Reading a run file

```json
{"address": "0x...", "raw_base": "https://raw.githubusercontent.com/...",
 "rounds": [{"case": "BASE-OK", "status": "FINALIZED", "observed": "FULFILLED",
             "seller_bps": 10000, "passed": true, "seconds": 68,
             "panel": [["C1", "SATISFIED"], ...],
             "nodes": [{"model": "...", "vote": "agree", "stdout": ""}]}]}
```

`vote` is `idle` for a node the round did not need (the leader does not vote).
A `passed` of `false` means the observed verdict or share fell outside what the
case expected - which is a finding about the case, the prompt or the contract,
and is worth reading before it becomes a live run.
