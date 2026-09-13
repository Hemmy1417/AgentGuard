"""The threat model, executed. Every on-chain case in fixtures/cases.json runs
twice: through the real commerce path (agreement, escrow, delivery, dispute,
adjudication, settlement) and through the on-chain adversarial-test engine.
Both must produce the catalogue's verdict and leave the seller inside its
share of the escrow."""

import json

import pytest

from tests.direct.support import (
    CASES, CATALOGUE, COMMERCE_CASES, ONCHAIN_CASES, PRICE, agreement, answer_for, as_sender,
    bundle_json, case_items, case_terms, claimable, commit, dispute, finding, present,
    register_case, stage, warp)

AFTER_APPEAL = "2026-09-16T12:00:01Z"


def run_through_commerce(guard, direct_vm, policy_id, case_id):
    """A case as two agents would actually live it."""
    entry = CASES[case_id]
    agreement_id = agreement(guard, direct_vm, policy_id, acceptance_criteria=case_terms(
        entry, policy_id)["acceptance_criteria"])
    seller_items = [i for i, e in zip(case_items(entry), entry["evidence"])
                    if e["party"] == "seller"]
    buyer_items = [i for i, e in zip(case_items(entry), entry["evidence"])
                   if e["party"] == "buyer"]
    ids = commit(guard, direct_vm, agreement_id, seller_items, "seller")
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, entry["seller_statement"] or "Delivered.")
    if buyer_items:
        commit(guard, direct_vm, agreement_id, buyer_items, "buyer")
    dispute(guard, direct_vm, agreement_id, entry["buyer_claim"] or "I dispute this.")
    stage(direct_vm, entry["panel_answer"])
    as_sender(direct_vm, "stranger")
    record = guard.get_adjudication(guard.request_adjudication(agreement_id))
    return agreement_id, record


def assert_case(record, entry):
    assert record["verdict"] == entry["expected_verdict"], record["reason_codes"]
    assert entry["expected_seller_bps_min"] <= record["seller_bps"] \
        <= entry["expected_seller_bps_max"], (record["seller_bps"], record["reason_codes"])
    escrow = int(record["escrow_atto"])
    seller = int(record["payment_allocation_atto"])
    buyer = int(record["refund_allocation_atto"])
    if record["settleable"]:
        assert seller + buyer == escrow
        assert seller == escrow * record["seller_bps"] // 10000
    else:
        assert seller == 0 and buyer == 0


def test_the_catalogue_covers_every_brief_attack(guard):
    categories = {c["attack_category"] for c in CATALOGUE["cases"]}
    brief = set(guard.get_config()["attack_categories"]) - {"LEGITIMATE_BASELINE",
                                                            "OTHER"}
    assert len(brief) == 30
    assert brief <= categories


@pytest.mark.parametrize("case_id", COMMERCE_CASES)
def test_case_through_the_commerce_path(guard, direct_vm, policy_id, case_id):
    _agreement_id, record = run_through_commerce(guard, direct_vm, policy_id, case_id)
    assert_case(record, CASES[case_id])


@pytest.mark.parametrize("case_id", ONCHAIN_CASES)
def test_case_through_the_engine(guard, direct_vm, policy_id, case_id):
    entry = CASES[case_id]
    onchain_id = register_case(guard, direct_vm, policy_id, case_id)
    stage(direct_vm, entry["panel_answer"])
    as_sender(direct_vm, "stranger")            # running a case is permissionless
    observed = guard.run_adversarial_case(onchain_id)
    view = guard.get_adversarial_case(onchain_id)
    assert observed == entry["expected_verdict"] == view["observed_verdict"]
    assert view["passed"] is True, view
    assert view["status"] == "RAN"
    record = guard.get_adjudication(view["receipt_id"])
    assert record["kind"] == "TEST" and record["case_id"] == onchain_id
    assert_case(record, entry)
    # a case moves nothing: no escrow, no ledger
    assert guard.health_check()["escrow_held_atto"] == "0"
    assert guard.health_check()["claimable_atto"] == "0"


# -- what particular attacks must show, beyond the verdict -----------------------

def test_the_sellers_own_word_is_never_a_fact(guard, direct_vm, policy_id):
    _id, record = run_through_commerce(guard, direct_vm, policy_id, "A01")
    assert record["verdict"] == "INSUFFICIENT_EVIDENCE"
    for criterion in ("C1", "C2", "C3"):
        assert finding(record, criterion)["state"] == "UNVERIFIABLE"
        assert finding(record, criterion)["by"] == "CODE"   # never even asked
    assert record["settleable"] is False


def test_a_false_rejection_does_not_cost_the_seller(guard, direct_vm, policy_id):
    agreement_id, record = run_through_commerce(guard, direct_vm, policy_id, "A02")
    assert record["verdict"] == "FULFILLED" and record["seller_bps"] == 10000
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    guard.finalize_settlement(agreement_id)
    assert claimable(guard, "seller") == PRICE
    assert claimable(guard, "buyer") == 0


def test_a_buyer_moving_the_goalposts_is_recorded(guard, direct_vm, policy_id):
    _id, record = run_through_commerce(guard, direct_vm, policy_id, "A07")
    assert record["verdict"] == "FULFILLED"
    assert "BUYER_CRITERIA_CHANGE" in present(record)
    assert record["buyer_fault_level"] == "PARTIAL"
    assert record["seller_bps"] == 10000


def test_withheld_access_costs_the_buyer_not_the_seller(guard, direct_vm, policy_id):
    # the premise is in the agreement itself: its first criterion needs the
    # buyer's input. Without it a panel reading the terms as the whole
    # standard finds nothing the buyer was required to give - as one did live
    assert [c["criterion_id"] for c in case_terms(CASES["A17"], policy_id)[
        "acceptance_criteria"] if c["requires_buyer_input"]] == ["C1"]
    agreement_id, record = run_through_commerce(guard, direct_vm, policy_id, "A17")
    assert record["verdict"] == "BUYER_NON_COOPERATION"
    assert record["buyer_fault_level"] == "FULL"
    assert record["seller_fault_level"] == "NONE"
    assert record["seller_bps"] == 7500
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    guard.finalize_settlement(agreement_id)
    assert claimable(guard, "seller") == PRICE * 7500 // 10000
    assert claimable(guard, "buyer") == PRICE - PRICE * 7500 // 10000


def test_a_legitimate_variation_is_not_a_breach(guard, direct_vm, policy_id):
    """The false-positive case the brief asks for: work that meets the
    criterion in a different but reasonable way is fulfilled."""
    _id, record = run_through_commerce(guard, direct_vm, policy_id, "A29")
    assert record["verdict"] == "FULFILLED" and record["seller_bps"] == 10000
    assert finding(record, "C4")["state"] == "SATISFIED"
    assert present(record) == []


def test_filing_a_document_is_not_meeting_the_criterion(guard, direct_vm, policy_id):
    """A30: the seller files something titled a method report which states no
    limitation at all. The criterion asks what the report says, not whether
    one exists, so its weight is lost and the split follows the level."""
    _id, record = run_through_commerce(guard, direct_vm, policy_id, "A30")
    assert finding(record, "C3")["state"] == "NOT_SATISFIED"
    assert record["verdict"] == "PARTIALLY_FULFILLED"
    assert record["fulfillment_level"] == 77          # 70 of the 90 counted weight
    assert record["seller_bps"] == 8440
    assert record["seller_fault_level"] == "PARTIAL"


def test_stale_and_foreign_logs_are_both_excluded(guard, direct_vm, policy_id):
    for case_id, indicator in (("A19", "STALE_EVIDENCE"),
                               ("A10", "EVIDENCE_UNLINKED")):
        _id, record = run_through_commerce(guard, direct_vm, policy_id, case_id)
        assert indicator in present(record), case_id
        assert finding(record, "C2")["state"] == "UNVERIFIABLE", case_id


def test_a_late_delivery_is_recorded_against_the_deadline(guard, direct_vm, policy_id):
    """The deadline and the cure period the two agents agreed, applied by the
    clock alone: a delivery inside the cure period is on time, and one past it
    is recorded as missed - by code, whatever the panel says about the work."""
    from tests.direct.support import adjudicate, answer, deliver, satisfied, warp
    one_criterion = answer({"C1": satisfied("E1", "Rows delivered: 5,250")})
    on_time = agreement(guard, direct_vm, policy_id)
    warp(direct_vm, "2026-09-16T11:00:00Z")     # deadline + 23h; the cure period is 24h
    deliver(guard, direct_vm, on_time)
    dispute(guard, direct_vm, on_time)
    record = adjudicate(guard, direct_vm, on_time, one_criterion)
    assert finding(record, "DEADLINE_MISSED")["state"] == "ABSENT"

    warp(direct_vm, "2026-09-13T12:00:00Z")
    late = agreement(guard, direct_vm, policy_id)
    warp(direct_vm, "2026-09-16T12:00:01Z")     # one second past the cure period
    deliver(guard, direct_vm, late)
    dispute(guard, direct_vm, late)
    record = adjudicate(guard, direct_vm, late, one_criterion)
    assert finding(record, "DEADLINE_MISSED")["state"] == "PRESENT"
    assert finding(record, "DEADLINE_MISSED")["by"] == "CODE"
    assert "INDICATOR:DEADLINE_MISSED" in record["reason_codes"]


def test_the_same_bytes_twice_cannot_look_like_two_deliveries(guard, direct_vm,
                                                              policy_id):
    """A09 through the engine: the commerce path refuses the second
    commitment outright, so the engine is where the indicator is visible -
    both copies excluded, and nothing either carries counted."""
    entry = CASES["A09"]
    onchain_id = register_case(guard, direct_vm, policy_id, "A09")
    stage(direct_vm, entry["panel_answer"])
    as_sender(direct_vm, "stranger")
    guard.run_adversarial_case(onchain_id)
    record = guard.get_adjudication(guard.get_adversarial_case(onchain_id)["receipt_id"])
    assert "DUPLICATE_EVIDENCE" in present(record)
    assert finding(record, "DUPLICATE_EVIDENCE")["evidence_ids"] == ["E1", "E2"]
    assert [r["counted"] for r in record["receipts"][:2]] == [False, False]
    assert record["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_the_registry_flags_the_later_commitment_never_the_first(guard, direct_vm,
                                                                 policy_id):
    """Two agreements, the same third party's record. The agreement that
    committed those bytes first keeps them unmarked; the one that reused them
    is flagged, and the artifact itself - a DELIVERABLE - is exempt, because
    the same work may honestly be sold twice."""
    from tests.direct.support import FULL_ANSWER, adjudicate, deliver
    note = ("THIRD_PARTY_RECORD", "sources/thirdparty/verifier-note.txt",
            "Meridian Data Assurance", "an independent spot check")
    first = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, first)
    commit(guard, direct_vm, first, [note], "seller")
    dispute(guard, direct_vm, first)
    first_record = adjudicate(guard, direct_vm, first, FULL_ANSWER)
    assert finding(first_record, "CROSS_AGREEMENT_REUSE")["state"] == "ABSENT"

    second = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, second)            # the same delivery, sold again
    commit(guard, direct_vm, second, [note], "seller")
    dispute(guard, direct_vm, second)
    second_record = adjudicate(guard, direct_vm, second, FULL_ANSWER)
    reuse = finding(second_record, "CROSS_AGREEMENT_REUSE")
    assert reuse["state"] == "PRESENT" and reuse["by"] == "REGISTRY"
    # the log, the receipt and the third party's note; not the two deliverables
    assert reuse["evidence_ids"] == ["E3", "E4", "E5"]
    assert guard.get_adjudication(first_record["adjudication_id"])["indicators"] == \
        first_record["indicators"]               # the first record is untouched


def test_a_case_simulating_the_committing_agreement_is_not_reuse(guard, direct_vm,
                                                                  policy_id):
    """A case simulates one agreement, and the registry is read for that
    agreement. When it is the agreement that committed the bytes, they are its
    own evidence. The live run is exactly this: phase A commits its delivery
    under AG-000001 and every phase B case simulates AG-000001. The same bytes
    simulated under any other agreement are flagged, so the engine does read
    the registry."""
    from tests.direct.support import deliver
    committed = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, committed)          # BASE-OK's four items
    assert json.loads(bundle_json(CASES["BASE-OK"]))["agreement_id"] == committed

    own = register_case(guard, direct_vm, policy_id, "BASE-OK")
    stage(direct_vm, answer_for("BASE-OK"))
    as_sender(direct_vm, "stranger")
    guard.run_adversarial_case(own)
    view = guard.get_adversarial_case(own)
    record = guard.get_adjudication(view["receipt_id"])
    assert finding(record, "CROSS_AGREEMENT_REUSE")["state"] == "ABSENT"
    assert view["passed"] is True

    bundle = json.loads(bundle_json(CASES["BASE-OK"]))
    bundle["agreement_id"] = "AG-000002"
    as_sender(direct_vm, "platform")
    other = guard.register_adversarial_case(policy_id, 1, "OTHER",
                                            "the same bytes under another agreement",
                                            json.dumps(bundle), "FULFILLED", 0, 10000)
    stage(direct_vm, answer_for("BASE-OK"))
    as_sender(direct_vm, "stranger")
    guard.run_adversarial_case(other)
    record = guard.get_adjudication(guard.get_adversarial_case(other)["receipt_id"])
    reuse = finding(record, "CROSS_AGREEMENT_REUSE")
    assert reuse["state"] == "PRESENT" and reuse["by"] == "REGISTRY"
    assert reuse["evidence_ids"] == ["E3", "E4"]  # the log and the receipt


# -- the engine itself -------------------------------------------------------------

def test_engine_permissions_and_single_run(guard, direct_vm, policy_id):
    entry = CASES["BASE-OK"]
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("only the policy owner can register a case"):
        guard.register_adversarial_case(policy_id, 1, "OTHER", "x", bundle_json(entry),
                                        "FULFILLED", 0, 10000)
    case_id = register_case(guard, direct_vm, policy_id, "BASE-OK")
    stage(direct_vm, answer_for("BASE-OK"))
    guard.run_adversarial_case(case_id)
    with direct_vm.expect_revert("case has already run"):
        guard.run_adversarial_case(case_id)
    assert guard.list_adversarial_cases(policy_id, 1, 0, 10) == {"total": 1,
                                                                 "items": [case_id]}


@pytest.mark.parametrize("mutate,message", [
    (lambda b: b.update(buyer="0xABC"), "buyer must be a lowercase 0x address"),
    (lambda b: b.update(seller=b["buyer"]), "cannot contract with itself"),
    (lambda b: b.update(evidence=[]), "evidence must hold"),
    (lambda b: b.update(evidence=b["evidence"] * 4), "evidence must hold"),
    (lambda b: b["evidence"].append(dict(b["evidence"][0])), "same location twice"),
    (lambda b: b.update(extra=1), "input_bundle keys"),
    (lambda b: b["evidence"][0].update(url="http://x.example.org/a"), "https"),
    (lambda b: b["evidence"][0].update(party="referee"), "party must be buyer or seller"),
    (lambda b: b["terms"].update(acceptance_criteria=[]), "acceptance_criteria"),
])
def test_engine_bundle_validation(guard, direct_vm, policy_id, mutate, message):
    bundle = json.loads(bundle_json(CASES["BASE-OK"]))
    mutate(bundle)
    as_sender(direct_vm, "platform")
    with direct_vm.expect_revert(message):
        guard.register_adversarial_case(policy_id, 1, "OTHER", "x", json.dumps(bundle),
                                        "FULFILLED", 0, 10000)


@pytest.mark.parametrize("category,verdict,low,high,message", [
    ("NOT_A_CATEGORY", "FULFILLED", 0, 10000, "attack_category"),
    ("OTHER", "MAYBE", 0, 10000, "expected_verdict"),
    ("OTHER", "FULFILLED", 5000, 4000, "expected seller bps"),
    ("OTHER", "FULFILLED", 0, 10001, "expected seller bps"),
])
def test_engine_case_fields(guard, direct_vm, policy_id, category, verdict, low, high,
                            message):
    as_sender(direct_vm, "platform")
    with direct_vm.expect_revert(message):
        guard.register_adversarial_case(policy_id, 1, category, "x",
                                        bundle_json(CASES["BASE-OK"]), verdict, low, high)


def test_a_case_fails_on_the_share_even_when_the_verdict_matches(guard, direct_vm,
                                                                 policy_id):
    """Both halves have to hold, or a change that moved only the money would
    be reported as harmless."""
    as_sender(direct_vm, "platform")
    case_id = guard.register_adversarial_case(
        policy_id, 1, "LEGITIMATE_BASELINE", "the baseline with impossible bounds",
        bundle_json(CASES["BASE-OK"]), "FULFILLED", 0, 100)
    stage(direct_vm, answer_for("BASE-OK"))
    assert guard.run_adversarial_case(case_id) == "FULFILLED"
    view = guard.get_adversarial_case(case_id)
    assert view["observed_seller_bps"] == 10000
    assert view["passed"] is False


def test_replaying_a_case_onto_a_new_policy_shows_the_change(guard, direct_vm,
                                                             policy_id):
    """A lender-side rule change, checked against a recorded attack before
    any agreement binds it: the same evidence, a different split."""
    from tests.direct.support import policy_json
    baseline = register_case(guard, direct_vm, policy_id, "A17")
    stage(direct_vm, answer_for("A17"))
    as_sender(direct_vm, "stranger")
    guard.run_adversarial_case(baseline)
    assert guard.get_adversarial_case(baseline)["observed_seller_bps"] == 7500
    as_sender(direct_vm, "platform")
    guard.publish_policy_version(policy_id,
                                 policy_json(buyer_non_cooperation_seller_bps=2500))
    replayed = guard.replay_adversarial_case(baseline, 2)
    stage(direct_vm, answer_for("A17"))
    as_sender(direct_vm, "stranger")
    guard.run_adversarial_case(replayed)
    view = guard.get_adversarial_case(replayed)
    assert view["source_case_id"] == baseline and view["policy_version"] == 2
    assert view["observed_verdict"] == "BUYER_NON_COOPERATION"
    assert view["observed_seller_bps"] == 2500
    assert view["passed"] is False        # the change is visible, and recorded


def test_replay_permissions(guard, direct_vm, policy_id):
    baseline = register_case(guard, direct_vm, policy_id, "BASE-OK")
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("only the policy owner can replay"):
        guard.replay_adversarial_case(baseline, 1)
    as_sender(direct_vm, "platform")
    with direct_vm.expect_revert("unknown target version"):
        guard.replay_adversarial_case(baseline, 5)
    guard.revoke_policy_version(policy_id, 1)
    with direct_vm.expect_revert("target version is revoked"):
        guard.replay_adversarial_case(baseline, 1)
    with direct_vm.expect_revert("policy version is revoked"):
        register_case(guard, direct_vm, policy_id, "BASE-OK")
