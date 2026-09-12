#!/usr/bin/env python3
"""Inspect an AgentGuard deployment on StudioNet - read-only, no stored key.

    python scripts/inspect_deployment.py                    # deploy/deployment.json
    python scripts/inspect_deployment.py 0xADDRESS
    python scripts/inspect_deployment.py 0xADDRESS AG-000001

Prints: whether the deployed source is byte-identical to
contracts/agentguard.py, the method count from the deployed schema,
health_check (including the escrow held and the claimable total), the
configured version and bounds, and - for the agreement id given, or for every
agreement the demo agents are party to - its settlement status as of now.
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
FIELDS = ("status", "verdict", "fulfillment_level", "seller_bps",
          "payment_allocation_atto", "refund_allocation_atto", "settleable",
          "appeal_window_open", "appeal_pending", "can_finalize_now",
          "can_claim_stalled_now", "finalized", "settlement_route",
          "settled_seller_atto", "settled_buyer_atto")


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
    health = read("health_check", [])
    print("health_check   ", health)
    config = read("get_config", [])
    print("version        ", config["contract_version"], " bounds", config["bounds"])

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    agreement_ids = []
    if len(args) > 1:
        agreement_ids.append(args[1])
    else:
        wallets = json.loads((ROOT / "fixtures" / "wallets.json").read_text(encoding="utf-8"))
        for wallet in wallets.values():
            listed = read("list_agent_agreements", [wallet, 0, 50])
            for agreement_id in listed.get("items") or []:
                if agreement_id not in agreement_ids:
                    agreement_ids.append(agreement_id)
    for agreement_id in agreement_ids:
        status = read("settlement_status", [agreement_id, now])
        if not status.get("found"):
            print(f"\n{agreement_id}: not found")
            continue
        print(f"\n{agreement_id}")
        for key in FIELDS:
            print(f"  {key:<24}{status.get(key)}")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
