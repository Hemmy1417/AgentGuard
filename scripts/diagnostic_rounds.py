#!/usr/bin/env python3
"""Disposable diagnostic deployment: which fields split validators on the
panel-decided cases? Not canonical - the results inform the design only and
are kept under deploy/diagnostics/.

  python scripts/diagnostic_rounds.py <raw-base> [CASE,CASE,...]

Deploys the working-tree contract from a fresh ephemeral account, registers
the demo settlement policy, and runs each case through the adversarial
engine. For every round it records each node's model, vote and the tail of
its stdout - the contract prints [DISAGREE], [DOWNGRADE] and
[MODEL_OUTPUT_INVALID] lines there, so a split names its own cause.

StudioNet validators span several model families; a format-strict answer can
split them. Diagnose that here, on a throwaway address, before the canonical
deployment.
"""

import importlib.util
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import studionet_transport  # noqa: E402,F401
from genlayer_py import create_account, create_client  # noqa: E402
from genlayer_py.chains import studionet  # noqa: E402
from genlayer_py.types import TransactionStatus  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = sys.argv[1] if len(sys.argv) > 1 else ""
CASE_IDS = sys.argv[2].split(",") if len(sys.argv) > 2 else [
    "BASE-OK", "A03", "A11", "A17", "A30", "BASE-OK", "A17"]
OUT = ROOT / "deploy" / "diagnostics" / ("run_" + time.strftime("%Y%m%dT%H%M%S") + ".json")

spec = importlib.util.spec_from_file_location("support", ROOT / "tests/direct/support.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
client = create_client(chain=studionet, account=create_account())
out = {"raw_base": RAW, "cases": CASE_IDS, "rounds": []}


def wait(tx):
    return client.wait_for_transaction_receipt(transaction_hash=tx,
                                               status=TransactionStatus.FINALIZED,
                                               interval=5000, retries=240)


def leader(r):
    lr = r["consensus_data"]["leader_receipt"]
    return str((lr[0] if isinstance(lr, list) else lr)["execution_result"])


def save():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")


r = wait(client.deploy_contract(code=(ROOT / "contracts/agentguard.py").read_text(
    encoding="utf-8"), args=[], consensus_max_rotations=3))
addr = r["data"]["contract_address"]
out["address"] = addr
print("deployed", addr, leader(r), flush=True)


def W(fn, args):
    return wait(client.write_contract(address=addr, function_name=fn, args=args,
                                      consensus_max_rotations=3))


def R(fn, args):
    return client.read_contract(address=addr, function_name=fn, args=args)


print("policy", leader(W("register_policy",
                         [json.dumps(support.policy_definition())])), flush=True)
for cid in CASE_IDS:
    entry = support.CASES[cid]
    W("register_adversarial_case", [
        "SP-000001", 1, entry["attack_category"], entry["notes"],
        support.bundle_json(entry, "SP-000001", RAW), entry["expected_verdict"],
        entry["expected_seller_bps_min"], entry["expected_seller_bps_max"]])
    case_id = R("list_adversarial_cases", ["SP-000001", 1, 0, 50])["items"][-1]
    t0 = time.time()
    r = W("run_adversarial_case", [case_id])
    cd = r["consensus_data"]
    nodes = []
    for n in [cd["leader_receipt"][0]] + cd.get("validators", []):
        nc = n["node_config"]
        nodes.append({"mode": n["mode"],
                      "model": (nc.get("primary_model") or {}).get("model"),
                      "vote": cd["votes"].get(nc["address"]),
                      "stdout": ((n.get("genvm_result") or {}).get("stdout") or "")[-600:]})
    view = R("get_adversarial_case", [case_id])
    rec = R("get_adjudication", [view["receipt_id"]]) if view["receipt_id"] else {}
    row = {"case": cid, "status": r.get("status_name"), "leader": leader(r),
           "seconds": round(time.time() - t0), "observed": view["observed_verdict"],
           "seller_bps": view["observed_seller_bps"], "passed": view["passed"],
           "panel": [(f["id"], f["state"]) for f in rec.get("criteria", []) + rec.get(
               "indicators", []) if f.get("by") == "PANEL"],
           "nodes": nodes}
    out["rounds"].append(row)
    save()
    print(cid, row["status"], row["observed"], row["seller_bps"], row["passed"],
          row["seconds"], "s",
          [(n["model"], n["vote"], n["stdout"].strip()[-160:]) for n in nodes], flush=True)
print("DONE", OUT.relative_to(ROOT), flush=True)
