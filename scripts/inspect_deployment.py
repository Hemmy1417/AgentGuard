#!/usr/bin/env python3
"""Inspect a AgentGuard deployment on StudioNet - read-only, no stored key.

    python scripts/inspect_deployment.py                    # deploy/deployment.json
    python scripts/inspect_deployment.py 0xADDRESS
    python scripts/inspect_deployment.py 0xADDRESS CA-000001

Prints: whether the deployed source is byte-identical to
contracts/agentguard.py, the method count from the deployed schema,
health_check, the configured version and bounds, and - when an assessment
id is given, or the demo wallets have assessments under LP-000001 - their
lender-facing status as of now.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

import studionet_transport  # noqa: F401 - retries RPC transport failures
from deploy_studionet import deployed_source, rpc
from genlayer_py import create_account, create_client
from genlayer_py.chains import studionet

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "agentguard.py"
RECORD = ROOT / "deploy" / "deployment.json"


def main() -> int:
    args = sys.argv[1:]
    address = args[0] if args else json.loads(RECORD.read_text(encoding="utf-8"))[
        "contract_address"]
    # genlayer-py reads need an account object; an ephemeral one signs nothing
    client = create_client(chain=studionet, account=create_account())
    read = lambda fn, a: client.read_contract(address=address, function_name=fn, args=a)  # noqa: E731

    deployed = deployed_source(address)
    local = CONTRACT.read_bytes()
    same = hashlib.sha256(deployed).hexdigest() == hashlib.sha256(local).hexdigest()
    print("contract       ", address)
    print("deployed sha256", hashlib.sha256(deployed).hexdigest())
    print("local sha256   ", hashlib.sha256(local).hexdigest())
    print("byte-identical ", same)
    schema = rpc("gen_getContractSchema", [address]).get("result") or {}
    print("schema methods ", len(schema.get("methods") or {}))
    print("health_check   ", read("health_check", []))
    config = read("get_config", [])
    print("version        ", config["contract_version"], " bounds", config["bounds"])

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    targets = []
    if len(args) > 1:
        targets.append(("", args[1]))
    else:
        wallets = json.loads((ROOT / "fixtures" / "wallets.json").read_text(encoding="utf-8"))
        for name, wallet in wallets.items():
            latest = read("get_latest_assessment", [wallet, "LP-000001", now])
            if latest.get("found"):
                targets.append((name, latest["assessment_id"]))
    for name, assessment_id in targets:
        status = read("assessment_status", [assessment_id, now])
        print(f"\n{assessment_id} {name}".rstrip())
        for key in ("verdict", "score", "risk_band", "recommended_exposure",
                    "recommended_ltv_bps", "eligible", "freshness", "consumable",
                    "finalized", "appeal_id"):
            print(f"  {key:<22}{status.get(key)}")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
