"""Consensus: the validator reproduces the round from its own fetch and its
own model call, gates the leader's payload against its own verified bytes,
and compares every field a settlement reads. These tests hand the captured
validator forged leader results and change the validator's world through the
mocks."""

import copy

from tests.direct.support import (
    DELIVERY, FULL_ANSWER, adjudicate, agreement, answer, captured_ctx,
    captured_payload, commit, deliver, dispute, mock_panel, satisfied, serve_all,
    serve_bytes, stage, url_of)


def validate(direct_vm, mod, payload) -> bool:
    text = payload if isinstance(payload, str) else mod._canonical(payload)
    return direct_vm.run_validator(leader_result=text)


def round_one(guard, direct_vm, policy_id, panel_answer=None):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    return adjudicate(guard, direct_vm, agreement_id, panel_answer or FULL_ANSWER)


def subject(payload, subject_id):
    for f in payload["criteria"] + payload["indicators"]:
        if f["id"] == subject_id:
            return f
    raise KeyError(subject_id)


def test_the_payload_carries_no_money(mod):
    """Nothing a leader proposes is an amount: the settlement fields are not
    in the payload at all, so validators agree on them by construction."""
    for key in ("verdict", "seller_bps", "payment_allocation_atto",
                "refund_allocation_atto", "fulfillment_level", "settleable",
                "seller_fault_level", "buyer_fault_level"):
        assert key not in mod.PAYLOAD_KEYS


def test_honest_leader_is_ratified(guard, direct_vm, policy_id):
    round_one(guard, direct_vm, policy_id)
    assert direct_vm.run_validator() is True


def test_prose_is_not_compared(guard, direct_vm, mod, policy_id):
    round_one(guard, direct_vm, policy_id)
    payload = captured_payload(direct_vm)
    subject(payload, "C1")["note"] = "a different sentence entirely"
    assert validate(direct_vm, mod, payload) is True


def test_a_leader_inventing_a_satisfied_criterion_is_refused(guard, direct_vm, mod,
                                                             policy_id):
    """The only route from a leader to the seller's money is a criterion
    state. The validator asked its own model and read its own bytes."""
    record = round_one(guard, direct_vm, policy_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    }))
    assert record["seller_bps"] == 7120
    payload = captured_payload(direct_vm)
    subject(payload, "C2")["state"] = "SATISFIED"
    assert validate(direct_vm, mod, payload) is False


def test_a_leader_hiding_a_code_finding_is_refused(guard, direct_vm, mod, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = commit(guard, direct_vm, agreement_id, [
        DELIVERY[0],
        ("EXECUTION_LOG", "sources/logs/other-agreement-log.json", "Runner Cloud",
         "the run log")])
    from tests.direct.support import as_sender
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250")}))
    payload = captured_payload(direct_vm)
    assert subject(payload, "EVIDENCE_UNLINKED")["state"] == "PRESENT"
    subject(payload, "EVIDENCE_UNLINKED").update(state="ABSENT", evidence_ids=[])
    assert validate(direct_vm, mod, payload) is False
    payload = captured_payload(direct_vm)
    payload["facts"][0]["agreement_id"] = "AG-000001"     # or rewriting the fact
    assert validate(direct_vm, mod, payload) is False


def test_a_rebound_round_is_refused(guard, direct_vm, mod, policy_id):
    round_one(guard, direct_vm, policy_id)
    for key, value in (("subject_id", "AD-000999"), ("terms_hash", "0" * 64),
                       ("evidence_commitment", "1" * 64),
                       ("now", "2027-01-01T00:00:00Z")):
        payload = captured_payload(direct_vm)
        payload[key] = value
        assert validate(direct_vm, mod, payload) is False, key


def test_an_invented_quote_is_refused(guard, direct_vm, mod, policy_id):
    round_one(guard, direct_vm, policy_id)
    payload = captured_payload(direct_vm)
    subject(payload, "C1")["quotes"] = [
        {"evidence_id": "E1", "text": "the buyer has agreed to pay in full"}]
    subject(payload, "C1")["evidence_ids"] = ["E1"]
    assert validate(direct_vm, mod, payload) is False


def test_a_forged_byte_count_is_refused(guard, direct_vm, mod, policy_id):
    round_one(guard, direct_vm, policy_id)
    payload = captured_payload(direct_vm)
    payload["rows"][0]["byte_count"] = payload["rows"][0]["byte_count"] + 1
    assert validate(direct_vm, mod, payload) is False


def test_a_payload_carrying_a_settlement_is_refused(guard, direct_vm, mod, policy_id):
    round_one(guard, direct_vm, policy_id)
    payload = captured_payload(direct_vm)
    payload["seller_bps"] = 10000
    assert validate(direct_vm, mod, payload) is False


def test_source_divergence_between_nodes(guard, direct_vm, policy_id):
    """The leader verified the bytes; this validator is served different
    bytes at the same location, records HASH_MISMATCH and disagrees."""
    round_one(guard, direct_vm, policy_id)
    direct_vm.clear_mocks()
    serve_bytes(direct_vm, url_of(DELIVERY[1][1]), b"a different method report")
    serve_all(direct_vm)
    mock_panel(direct_vm, FULL_ANSWER)
    assert direct_vm.run_validator() is False


def test_a_source_this_validator_cannot_reach(guard, direct_vm, policy_id):
    round_one(guard, direct_vm, policy_id)
    stage(direct_vm, FULL_ANSWER, skip=(DELIVERY[0][1],))
    assert direct_vm.run_validator() is False


def test_validators_disagreeing_about_partial_fulfillment(guard, direct_vm, policy_id):
    """The brief's case: one node reads a criterion as met and another does
    not. That difference changes the split, so it is preserved."""
    round_one(guard, direct_vm, policy_id)
    other = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    })
    stage(direct_vm, other)
    assert direct_vm.run_validator() is False


def test_a_validator_undecided_where_the_leader_decided(guard, direct_vm, policy_id):
    round_one(guard, direct_vm, policy_id)
    undecided = answer({
        "C1": {"state": "UNVERIFIABLE", "quotes": [], "note": ""},
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    })
    stage(direct_vm, undecided)
    assert direct_vm.run_validator() is False


def test_a_leader_claiming_the_model_failed(guard, direct_vm, mod, policy_id):
    round_one(guard, direct_vm, policy_id)
    payload = captured_payload(direct_vm)
    payload["panel_state"] = "MODEL_OUTPUT_INVALID"
    for i, f in enumerate(payload["criteria"]):
        if f["by"] == "PANEL":
            payload["criteria"][i] = mod._finding(f["id"], "UNVERIFIABLE", "PANEL")
    for i, f in enumerate(payload["indicators"]):
        if f["by"] == "PANEL":
            payload["indicators"][i] = mod._finding(f["id"], "UNDETERMINED", "PANEL")
    assert validate(direct_vm, mod, payload) is False      # this model answered
    stage(direct_vm, {"nothing": "useful"})
    assert validate(direct_vm, mod, payload) is True       # both really failed


def test_leader_errors(guard, direct_vm, policy_id):
    round_one(guard, direct_vm, policy_id)
    assert direct_vm.run_validator(
        leader_error=Exception("[TRANSIENT] the model call failed")) is False
    assert direct_vm.run_validator(leader_error=Exception("[LLM_ERROR] garbage")) is False
    stage(direct_vm)                                        # model unreachable here too
    assert direct_vm.run_validator(
        leader_error=Exception("[TRANSIENT] the model call failed")) is True
    assert direct_vm.run_validator(leader_error=Exception("[LLM_ERROR] garbage")) is False


def test_vote_table_pure(mod, genlayer_vm):
    def raising(text):
        def run():
            raise genlayer_vm.UserError(text)
        return run

    E = genlayer_vm.UserError
    assert mod._vote_on_leader_error(E("[EXPECTED] x"), raising("[EXPECTED] x")) is True
    assert mod._vote_on_leader_error(E("[EXPECTED] x"), raising("[EXPECTED] y")) is False
    assert mod._vote_on_leader_error(E("[EXPECTED] x"), lambda: None) is False
    assert mod._vote_on_leader_error(E("[TRANSIENT] a"), raising("[TRANSIENT] b")) is True
    assert mod._vote_on_leader_error(E("[TRANSIENT] a"), raising("[EXPECTED] b")) is False
    assert mod._vote_on_leader_error(E("[LLM_ERROR] a"), raising("[LLM_ERROR] a")) is False
    assert mod._vote_on_leader_error("not an error", lambda: None) is False


def test_the_gate_is_strict_about_shape(guard, direct_vm, mod, policy_id):
    round_one(guard, direct_vm, policy_id)
    honest = captured_payload(direct_vm)
    forgeries = []
    for change in ("row_status", "float_fact", "bool_fact", "dropped_scan",
                   "short_indicators", "wrong_layer", "note_with_newline"):
        p = copy.deepcopy(honest)
        if change == "row_status":
            p["rows"][0]["status"] = "FETCHED"
        elif change == "float_fact":
            p["facts"][0]["values"]["runs"] = 3.0
        elif change == "bool_fact":
            p["facts"][0]["values"]["runs"] = True
        elif change == "dropped_scan":
            p["linked"] = []
        elif change == "short_indicators":
            p["indicators"] = p["indicators"][:-1]
        elif change == "wrong_layer":
            subject(p, "C1")["by"] = "CODE"
        else:
            subject(p, "C1")["note"] = "line\nbreak"
        forgeries.append((change, p))
    for name, forged in forgeries:
        assert validate(direct_vm, mod, forged) is False, name
    assert validate(direct_vm, mod, "not json") is False
    assert validate(direct_vm, mod, honest) is True


def test_the_gate_alone_refuses_forgeries(guard, direct_vm, mod, policy_id):
    """_parse_payload runs again on the ratified text before anything is
    stored or paid, and recomputes every code-decided field without any
    validator's own round."""
    round_one(guard, direct_vm, policy_id)
    ctx = captured_ctx(direct_vm)
    honest = captured_payload(direct_vm)
    texts = mod._node_round(ctx)[1]
    assert mod._parse_payload(mod._canonical(honest), ctx, texts) is not None
    for change in ("indicator", "panel_reason", "marker", "quote", "criterion_state"):
        forged = copy.deepcopy(honest)
        if change == "indicator":
            subject(forged, "DUPLICATE_EVIDENCE")["state"] = "PRESENT"
        elif change == "panel_reason":
            forged["panel_reason"] = "NOTHING_TO_ASSESS"
        elif change == "marker":
            forged["markers"] = ["E1"]
        elif change == "quote":
            subject(forged, "C1")["quotes"] = [
                {"evidence_id": "E1", "text": "words that are not in the file"}]
        else:
            subject(forged, "C1").update(state="SATISFIED", quotes=[], evidence_ids=[])
        assert mod._parse_payload(mod._canonical(forged), ctx, texts) is None, change


def test_equivalence_statement_is_published(guard, mod):
    """A reviewer can read the rule the validators actually apply, from the
    contract itself."""
    published = guard.get_config()["equivalence"]
    assert published == mod.EQUIVALENCE_STATEMENT
    assert "hash-verifying every allowed evidence item itself" in published
    assert "no model output reaches an amount" in published
