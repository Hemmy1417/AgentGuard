"""Smoke: the public surface end to end - agents, a settlement policy, an
agreement, escrow, delivery, and both ways an agreement can close: the buyer
accepting, and an adjudicated dispute that pays out through the ledger."""

import json
import os
import pathlib

from tests.direct.support import (
    DELIVERY, FULL_ANSWER, NOW, PRICE, adjudicate, agreement, as_sender,
    assert_conserved, claimable, deliver, dispute, finding, policy_definition,
    receipt, setup, terms_definition, wallet, warp)


def test_config_and_health(guard):
    config = guard.get_config()
    assert config["contract_version"] == "0.1.0"
    assert len(config["attack_categories"]) == 32
    assert "PARTIALLY_FULFILLED" in config["verdicts"]
    assert set(config["holding_verdicts"]).isdisjoint(config["settling_verdicts"])
    health = guard.health_check()
    assert health["ok"] is True
    assert health["escrow_held_atto"] == "0" and health["claimable_atto"] == "0"


def test_agent_identity_is_the_signing_wallet(guard, direct_vm):
    as_sender(direct_vm, "buyer")
    returned = guard.register_agent(json.dumps(["research", "data purchasing"]))
    assert returned == wallet("buyer")
    profile = guard.get_agent(wallet("buyer"))
    assert profile["found"] and profile["agent_id"] == wallet("buyer")
    assert profile["owner_or_controller"] == wallet("buyer")
    assert profile["capabilities"] == ["research", "data purchasing"]


def test_policy_is_canonical_and_hashed(guard, direct_vm, policy_id):
    assert policy_id == "SP-000001"
    view = guard.get_policy(policy_id, 0)
    assert view["found"] and view["version"] == 1 and view["status"] == "ACTIVE"
    assert view["policy"] == policy_definition()
    assert len(view["policy_hash"]) == 64
    assert view["owner"] == wallet("platform")


def test_the_agreement_is_frozen_at_assent(guard, direct_vm, policy_id):
    as_sender(direct_vm, "buyer")
    agreement_id = guard.propose_agreement(wallet("seller"),
                                           json.dumps(terms_definition(policy_id)))
    assert agreement_id == "AG-000001"
    proposed = guard.get_agreement(agreement_id)
    assert proposed["status"] == "PROPOSED" and proposed["terms_hash"] == ""
    as_sender(direct_vm, "seller")
    terms_hash = guard.accept_agreement(agreement_id)
    accepted = guard.get_agreement(agreement_id)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["terms_hash"] == terms_hash and len(terms_hash) == 64
    assert accepted["terms"] == terms_definition(policy_id)
    assert accepted["policy_version"] == 1
    assert accepted["price_atto"] == str(PRICE)


def test_escrow_is_exactly_the_price(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id, fund=False)
    as_sender(direct_vm, "buyer")
    direct_vm.value = PRICE - 1
    with direct_vm.expect_revert("send exactly the agreed price"):
        guard.fund_escrow(agreement_id)
    direct_vm.value = PRICE
    guard.fund_escrow(agreement_id)
    direct_vm.value = 0
    view = guard.get_agreement(agreement_id)
    assert view["status"] == "FUNDED" and view["escrow_atto"] == str(PRICE)
    assert guard.health_check()["escrow_held_atto"] == str(PRICE)


def test_buyer_accepting_pays_the_seller_in_full(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    view = guard.get_delivery(agreement_id)
    assert view["found"] and len(view["deliverable_references"]) == len(DELIVERY)
    as_sender(direct_vm, "buyer")
    guard.accept_delivery(agreement_id)
    settled = guard.get_agreement(agreement_id)
    assert settled["status"] == "FINALIZED"
    assert settled["settlement_route"] == "BUYER_ACCEPTED"
    assert settled["settled_seller_atto"] == str(PRICE)
    assert settled["settled_buyer_atto"] == "0"
    assert claimable(guard, "seller") == PRICE and claimable(guard, "buyer") == 0
    assert_conserved(guard, PRICE, "seller", "buyer")


def test_withdraw_pays_once(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    as_sender(direct_vm, "buyer")
    guard.accept_delivery(agreement_id)
    as_sender(direct_vm, "seller")
    assert guard.withdraw() == str(PRICE)
    assert claimable(guard, "seller") == 0
    with direct_vm.expect_revert("nothing to withdraw"):
        guard.withdraw()
    assert guard.health_check()["claimable_atto"] == "0"


def test_a_dispute_adjudicated_and_settled(guard, direct_vm, policy_id):
    """The long way round: deliver, dispute, adjudicate, wait out the appeal
    window, finalize. The seller is paid what the verdict says, and the
    escrow reconciles to the wei."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id, "The row count looks short to me.")
    record = adjudicate(guard, direct_vm, agreement_id, FULL_ANSWER)
    assert record["verdict"] == "FULFILLED"
    assert record["fulfillment_level"] == 100
    assert record["seller_bps"] == 10000
    assert record["payment_allocation_atto"] == str(PRICE)
    assert record["refund_allocation_atto"] == "0"
    assert record["settleable"] is True
    assert record["seller_fault_level"] == "NONE" and record["buyer_fault_level"] == "NONE"
    assert record["kind"] == "ADJUDICATION"
    out = pathlib.Path(os.environ["AGENTGUARD_SAMPLE_OUT"]) \
        if os.environ.get("AGENTGUARD_SAMPLE_OUT") else None
    if out:
        out.write_text(json.dumps(record, indent=2), encoding="utf-8")

    status = guard.settlement_status(agreement_id, NOW)
    assert status["appeal_window_open"] is True and status["can_finalize_now"] is False
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("appeal window is still open"):
        guard.finalize_settlement(agreement_id)
    assert guard.health_check()["escrow_held_atto"] == str(PRICE)

    warp(direct_vm, "2026-09-16T12:00:01Z")
    as_sender(direct_vm, "stranger")            # finalizing is permissionless
    assert guard.finalize_settlement(agreement_id) == "FULFILLED"
    assert claimable(guard, "seller") == PRICE
    assert_conserved(guard, PRICE, "seller", "buyer")
    assert guard.get_agreement(agreement_id)["settlement_route"] == "ADJUDICATED"


def test_the_receipts_say_what_was_read(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, FULL_ANSWER)
    summary = receipt(record, "E1")
    assert summary["hash_verified"] and summary["trusted"] and summary["allowed"]
    assert summary["status"] == "EXAMINED" and summary["counted"] is True
    assert summary["submitted_by"] == "seller"
    assert summary["conflict_status"] == "SUPPORTS_A_FINDING"
    log = receipt(record, "E3")
    assert log["relevance_status"] == "LINKED"
    assert "runs=3" in log["summary"] and "succeeded=3" in log["summary"]
    assert finding(record, "C1")["by"] == "PANEL"
    assert finding(record, "C4")["state"] == "NOT_APPLICABLE"   # optional, unevidenced
    assert "CRITERION:C1:SATISFIED" in record["reason_codes"]
    assert record["reasoning_summary"].startswith("FULFILLED: fulfillment 100/100")
    assert "seller 400.00 GEN" in record["reasoning_summary"]


def test_views_for_a_counterparty(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = deliver(guard, direct_vm, agreement_id)
    status = guard.settlement_status(agreement_id, NOW)
    assert status["status"] == "DELIVERED" and status["verdict"] == ""
    assert status["escrow_atto"] == str(PRICE)
    assert status["can_claim_stalled_now"] is False
    assert guard.get_evidence(ids[0])["submitted_by"] == "seller"
    assert guard.get_evidence("EV-999999") == {"found": False,
                                               "evidence_id": "EV-999999"}
    assert guard.get_agreement("AG-999999")["found"] is False
    listed = guard.list_agent_agreements(wallet("seller"), 0, 10)
    assert listed == {"total": 1, "items": [agreement_id]}


def test_record_digest_covers_the_record(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, FULL_ANSWER)
    body = dict(record)
    del body["found"]
    digest = body.pop("record_digest")
    import hashlib
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == digest


def test_a_second_agreement_between_the_same_agents(guard, direct_vm, policy_id):
    first = agreement(guard, direct_vm, policy_id)
    second = agreement(guard, direct_vm, policy_id)
    assert (first, second) == ("AG-000001", "AG-000002")
    assert guard.health_check()["escrow_held_atto"] == str(2 * PRICE)
    deliver(guard, direct_vm, first)
    as_sender(direct_vm, "buyer")
    guard.accept_delivery(first)
    assert claimable(guard, "seller") == PRICE
    assert guard.health_check()["escrow_held_atto"] == str(PRICE)   # the second stands
    assert guard.get_agreement(second)["status"] == "FUNDED"


def test_setup_is_idempotent_for_other_agents(guard, direct_vm):
    policy_id = setup(guard, direct_vm)
    as_sender(direct_vm, "buyer")
    with direct_vm.expect_revert("already registered"):
        guard.register_agent(json.dumps(["again"]))
    assert policy_id == "SP-000001"
    assert guard.health_check()["agents"] == 2
