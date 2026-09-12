#!/usr/bin/env python3
"""Run one sample commerce dispute in Direct Mode and print it readably.

    python scripts/run_direct_mode.py            # readable summary
    python scripts/run_direct_mode.py --json     # the full stored record

The sample is the honest delivery disputed by its buyer: two agents, an
escrow, four evidence items, one consensus round, and the settlement the
contract derives from it. It runs the real contract in the official
genlayer-test direct runner, with the fixture documents served byte for byte
and the panel answered from fixtures/cases.json. No network, no keys, no
funds.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST = "tests/direct/test_contract_smoke.py::test_a_dispute_adjudicated_and_settled"
ATTO = 10 ** 18


def gen(atto) -> str:
    atto = int(atto)
    whole = atto // ATTO
    rest = (atto % ATTO) * 100 // ATTO
    return format(whole, ",") + "." + str(rest).zfill(2) + " GEN"


def show(record: dict) -> None:
    print("AgentGuard sample adjudication (Direct Mode)")
    print("=" * 66)
    print(f"adjudication    {record['adjudication_id']}  ({record['kind']})")
    print(f"agreement       {record['agreement_id']}   terms "
          f"{record['terms_hash'][:16]}...")
    print(f"buyer agent     {record['buyer']}")
    print(f"seller agent    {record['seller']}")
    print(f"escrow          {gen(record['escrow_atto'])}")
    print()
    print(f"verdict         {record['verdict']}   settles: {record['settleable']}")
    print(f"fulfillment     {record['fulfillment_level']}/100   confidence "
          f"{record['confidence']}")
    print(f"fault           seller {record['seller_fault_level']}, "
          f"buyer {record['buyer_fault_level']}")
    print(f"settlement      seller {gen(record['payment_allocation_atto'])}  "
          f"({record['seller_bps']} bps), buyer "
          f"{gen(record['refund_allocation_atto'])}")
    print(f"appeal until    {record['appeal_deadline']}")
    print()
    print("acceptance criteria")
    for f in record["criteria"]:
        quotes = "; ".join('"' + q["text"] + '"' for q in f["quotes"])
        print(f"  {f['id']:<4}{f['state']:<15}by {f['by']:<9}{quotes[:60]}")
    print()
    print("evidence receipts")
    print(f"  {'id':<4}{'category':<20}{'by':<8}{'status':<11}{'counted':<9}relevance")
    for r in record["receipts"]:
        print(f"  {r['evidence_id']:<4}{r['source_type']:<20}{r['submitted_by']:<8}"
              f"{r['status']:<11}{str(r['counted']):<9}{r['relevance_status']}")
    flagged = [f for f in record["indicators"] if f["state"] not in ("ABSENT",
                                                                     "NOT_APPLICABLE")]
    if flagged:
        print()
        print("indicators")
        for f in flagged:
            print(f"  {f['id']}: {f['state']} (by {f['by']})")
    print()
    print("reason codes")
    print("  " + ", ".join(record["reason_codes"]))
    print()
    print("summary")
    print("  " + record["reasoning_summary"])


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "record.json"
        env = dict(os.environ, AGENTGUARD_SAMPLE_OUT=str(out))
        run = subprocess.run([sys.executable, "-m", "pytest", TEST, "-q", "-p",
                              "no:cacheprovider"], cwd=ROOT, env=env,
                             capture_output=True, text=True)
        if run.returncode != 0 or not out.exists():
            print(run.stdout[-3000:], run.stderr[-2000:])
            print("the sample adjudication did not complete")
            return 1
        record = json.loads(out.read_text(encoding="utf-8"))
    if "--json" in sys.argv:
        print(json.dumps(record, indent=2))
    else:
        show(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
