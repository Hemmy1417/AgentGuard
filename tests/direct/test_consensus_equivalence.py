"""Consensus: the validator reproduces the round from its own fetch and its
own model call, gates the leader's payload against its own verified bytes,
and compares every field a settlement reads. These tests hand the captured
validator forged leader results and change the validator's world through the
mocks."""

import copy

import pytest

from tests.direct.support import (
    DELIVERY, FULL_ANSWER, adjudicate, agreement, answer, captured_ctx,
    captured_payload, commit, deliver, dispute, file_bytes, finding, mock_panel,
    satisfied, serve_all, serve_bytes, stage, url_of)


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


def test_a_fault_only_question_undecided_is_not_a_split(guard, direct_vm, policy_id):
    """BUYER_CRITERIA_CHANGE records fault and never moves money, and the
    fault level follows PRESENT alone. A validator whose model left it
    undecided reaches every consequence the leader's ABSENT reaches, so it
    ratifies. On StudioNet six disagreements were exactly this."""
    round_one(guard, direct_vm, policy_id)            # the leader: all ABSENT
    stage(direct_vm, answer(
        {"C1": satisfied("E1", "Rows delivered: 5,250"),
         "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
         "C3": satisfied("E2", "The enrichment ran in three passes")},
        {"BUYER_CRITERIA_CHANGE": {"state": "UNDETERMINED", "quotes": [], "note": ""}}))
    assert direct_vm.run_validator() is True


def test_a_fault_is_compared_on_whether_it_was_established(mod):
    """Where a finding has a consequence it is compared: an established fault
    against an unestablished one, and any difference in a question that can
    change the verdict - where UNDETERMINED holds the escrow."""
    def finding_of(subject_id, state):
        return {"id": subject_id, "state": state, "by": "PANEL", "quotes": [],
                "note": ""}
    fault = "BUYER_CRITERIA_CHANGE"
    assert mod.FAULT_ONLY_INDICATORS == (fault,)
    assert mod._same_reading(finding_of(fault, "ABSENT"), finding_of(fault, "UNDETERMINED"))
    assert not mod._same_reading(finding_of(fault, "PRESENT"),
                                 finding_of(fault, "UNDETERMINED"))
    assert not mod._same_reading(finding_of(fault, "ABSENT"), finding_of(fault, "PRESENT"))
    for outcome in mod.OUTCOME_INDICATORS:
        assert not mod._same_reading(finding_of(outcome, "ABSENT"),
                                     finding_of(outcome, "UNDETERMINED")), outcome
    assert not mod._same_reading(finding_of("C1", "SATISFIED"),
                                 finding_of("C1", "UNVERIFIABLE"))


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
                   "short_indicators", "wrong_layer", "note_with_newline",
                   "unfetched_bytes", "refused_allowed_item", "dropped_fact"):
        p = copy.deepcopy(honest)
        if change == "unfetched_bytes":
            # a byte count for bytes this node never verified
            p["rows"][0].update(status="UNAVAILABLE", byte_count=412)
        elif change == "refused_allowed_item":
            # an item the agreement allows, reported as outside the allowlist
            p["rows"][0].update(status="NOT_ALLOWED", byte_count=0)
        elif change == "dropped_fact":
            p["facts"] = p["facts"][1:]
        elif change == "row_status":
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
    grounded = subject(honest, "C1")["quotes"][0]["text"]
    over_cap = " ".join(texts["E1"].split())[:mod.QUOTE_CAP + 40]
    assert len(over_cap) > mod.QUOTE_CAP
    for change in ("indicator", "panel_reason", "marker", "quote", "criterion_state",
                   "layer", "fixed_finding", "ineligible_id", "unread_scan",
                   "long_quote", "too_many_quotes", "extra_key", "unsupported_finding",
                   "unquoted_decision", "dropped_fact"):
        forged = copy.deepcopy(honest)
        if change == "unquoted_decision":
            # a criterion decided with nothing quoted to show it
            subject(forged, "C1")["quotes"] = []
        elif change == "dropped_fact":
            # a structured item this node read, its facts left out
            forged["facts"] = forged["facts"][1:]
        elif change == "indicator":
            subject(forged, "DUPLICATE_EVIDENCE")["state"] = "PRESENT"
        elif change == "panel_reason":
            forged["panel_reason"] = "NOTHING_TO_ASSESS"
        elif change == "marker":
            forged["markers"] = ["E1"]
        elif change == "quote":
            subject(forged, "C1")["quotes"] = [
                {"evidence_id": "E1", "text": "words that are not in the file"}]
        elif change == "layer":
            # a panel reading presented as something code decided
            subject(forged, "C1")["by"] = "CODE"
        elif change == "fixed_finding":
            # C4 has no evidence of its categories, so code fixed it as
            # NOT_APPLICABLE before any model was asked
            subject(forged, "C4").update(state="SATISFIED", by="PANEL")
        elif change == "ineligible_id":
            subject(forged, "C1")["evidence_ids"] = ["E1", "E9"]
        elif change == "unread_scan":
            forged["linked"] = ["E9"]
        elif change == "long_quote":
            subject(forged, "C1")["quotes"] = [{"evidence_id": "E1", "text": over_cap}]
        elif change == "too_many_quotes":
            subject(forged, "C1")["quotes"] = [{"evidence_id": "E1", "text": grounded}
                                               for _ in range(mod.MAX_QUOTES + 1)]
        elif change == "extra_key":
            subject(forged, "C1")["confidence"] = "high"
        else:
            # a finding that favours the seller, resting only on the seller's
            # own summary
            subject(forged, "BUYER_WITHHELD_INPUT").update(
                state="PRESENT", evidence_ids=["E1"],
                quotes=[{"evidence_id": "E1", "text": grounded}])
        assert mod._parse_payload(mod._canonical(forged), ctx, texts) is None, change


def test_the_gate_alone_holds_rows_to_the_allowlist(guard, direct_vm, mod, policy_id):
    """A row for an item outside the frozen prefixes says NOT_ALLOWED and
    carries no bytes. A validator's own comparison would refuse either
    forgery too; these pin the gate by itself, which is all that stands
    between a ratified payload and the store."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id, items=[
        DELIVERY[0], DELIVERY[2],
        ("API_RECEIPT", "impostor/geocodex-official-receipt.json", "Geocodex",
         "the upstream receipt")])
    dispute(guard, direct_vm, agreement_id)
    adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E2", "\"status\": \"SUCCEEDED\"")}))
    ctx = captured_ctx(direct_vm)
    honest = captured_payload(direct_vm)
    texts = mod._node_round(ctx)[1]
    assert honest["rows"][2]["status"] == "NOT_ALLOWED"
    assert mod._parse_payload(mod._canonical(honest), ctx, texts) is not None
    for change, row in (("reported_unreachable", {"status": "UNAVAILABLE"}),
                        ("bytes_for_a_refused_item", {"byte_count": 412})):
        forged = copy.deepcopy(honest)
        forged["rows"][2].update(row)
        assert mod._parse_payload(mod._canonical(forged), ctx, texts) is None, change


# -- the grounding primitive ---------------------------------------------------

SOURCE = {"E1": "Rows delivered: 5,250\nColumns added: geo_lat, geo_lon\n"
                "The enrichment ran in three passes over the dataset.",
          "E2": "An independent check found no fabricated rows.",
          "E3": " ".join("the enrichment reconciled batch %d of the delivery" % i
                         for i in range(20))}


def grounds(mod, text, evidence_id="E1", eligible=("E1", "E2")):
    return mod._quote_grounded({"evidence_id": evidence_id, "text": text},
                               list(eligible), SOURCE)


def test_a_quote_grounds_only_in_the_bytes_it_cites(mod):
    assert grounds(mod, "Rows delivered: 5,250")
    assert grounds(mod, "ran in three passes")
    assert not grounds(mod, "Rows delivered: 6,000")      # not in the document
    assert not grounds(mod, "Rows delivered: 5,250", "E2")  # not in THAT document
    # E3's bytes do say this; E3 is simply not an item the round may count,
    # with or without the texts to check against
    assert grounds(mod, "the enrichment reconciled batch 3", "E3", ("E3",))
    assert not grounds(mod, "the enrichment reconciled batch 3", "E3")
    assert not mod._quote_grounded({"evidence_id": "E3",
                                    "text": "the enrichment reconciled batch 3"},
                                   ["E1", "E2"], None)
    assert not grounds(mod, "no fabricated rows", "E1")
    assert grounds(mod, "no fabricated rows", "E2")


def test_a_quote_may_elide_but_not_reorder(mod):
    assert grounds(mod, "Rows delivered: 5,250 ... ran in three passes")
    assert grounds(mod, "Columns added: geo_lat\nThe enrichment ran")
    # the same two fragments the other way round are not what the file says
    assert not grounds(mod, "ran in three passes ... Rows delivered: 5,250")


LOG = {"E1": '{\n  "runs": [\n    {\n      "run_id": "run-1",\n'
              '      "started": "2026-09-14T06:00:00Z",\n'
              '      "finished": "2026-09-14T06:00:01Z",\n'
              '      "status": "SUCCEEDED",\n      "items_processed": 5250\n'
              '    }\n  ]\n}'}


def in_log(mod, text):
    return mod._quote_grounded({"evidence_id": "E1", "text": text}, ["E1"], LOG)


def test_a_reflowed_json_quote_grounds_like_an_elision(mod):
    """A model quoting a structured item reflows its lines onto one and joins
    them with a comma. That is the claim an ellipsis makes, so it is read the
    same way and held to the same rule: every part present, in order. A live
    round lost a correct fabrication finding to this before the fallback."""
    assert in_log(mod, '"started": "2026-09-14T06:00:00Z", "finished": '
                       '"2026-09-14T06:00:01Z", "items_processed": 5250')
    assert in_log(mod, '"started": "2026-09-14T06:00:00Z" ... "items_processed": 5250')
    # the same latitude, not more: a part the document does not carry...
    assert not in_log(mod, '"started": "2026-09-14T06:00:00Z", '
                           '"items_processed": 9999')
    # ...and parts out of the document's own order
    assert not in_log(mod, '"items_processed": 5250, "started": '
                           '"2026-09-14T06:00:00Z"')


def test_a_run_needs_more_than_one_word(mod):
    """A single word occurs in half the corpus; a finding resting on one is
    not grounded in anything. Every run carries at least two, and a quote
    with no words at all grounds nothing."""
    assert not grounds(mod, "enrichment")
    assert not grounds(mod, "Rows delivered: 5,250 ... enrichment")
    assert grounds(mod, "the enrichment")
    assert not grounds(mod, "... ... ...")


def test_line_breaks_are_the_documents_not_the_quotes(mod):
    """A verbatim copy of a wrapped paragraph keeps the document's own line
    breaks, and its last line may be one word. On StudioNet four validators
    quoted A16's delivery summary exactly like this and lost the quote,
    because a line break was read as an elision and "run." as a fragment of
    one word."""
    summary = {"E1": file_bytes("sources/delivery/partial-dataset-summary.txt").decode()}
    sentence = ("The upstream endpoint began refusing requests part way through "
                "the second\nrun.")
    assert mod._quote_grounded({"evidence_id": "E1", "text": sentence}, ["E1"], summary)
    elided = "ENRICHED DATASET - DELIVERY SUMMARY ... " + sentence
    assert mod._quote_grounded({"evidence_id": "E1", "text": elided}, ["E1"], summary)
    # the method report ends the same way; its limitations are the likeliest quote
    report = {"E1": file_bytes("sources/delivery/method-report.txt").decode()}
    last = "No row was invented, and no value was copied from another\nrow."
    assert mod._quote_grounded({"evidence_id": "E1", "text": last}, ["E1"], report)


def test_joined_lines_ground_as_runs_of_two_words_or_more(mod):
    """Lines quoted from different places are found in order, and lines that
    follow each other in the document are one run. A one-word line from
    elsewhere stands alone, and grounds nothing."""
    assert grounds(mod, "Rows delivered: 5,250\n"
                        "The enrichment ran in three passes over the\ndataset.")
    assert not grounds(mod, "Rows delivered: 5,250\nenrichment\nover the dataset")
    assert not grounds(mod, "Rows delivered: 5,250\nenrichment")
    # a line the document does not have, even between two it does
    assert not grounds(mod, "Rows delivered: 5,250\nColumns removed: none\n"
                            "The enrichment ran")
    # and the document's order only
    assert not grounds(mod, "The enrichment ran\nColumns added: geo_lat")


def test_a_wrapped_run_is_sought_whole_before_its_lines(mod):
    """A part is sought as one run first, so a phrase the document also uses
    earlier cannot pull a first line away from the one-word line that
    completes it."""
    texts = {"E1": "The file was delivered late. The file was\ncorrupt."}
    assert mod._quote_grounded({"evidence_id": "E1", "text": "The file was\ncorrupt."},
                               ["E1"], texts)


def test_a_quote_is_kept_only_between_the_minimum_and_the_cap(mod):
    """_ground_quote is where a model's quote becomes a stored one: too
    short to identify anything is dropped, and an over-long one is trimmed to
    the cap at a word boundary and must still ground."""
    assert mod._ground_quote("passes", None, ["E1"], SOURCE) is None
    # two words the document does say, and still too short to identify anything
    assert mod._ground_quote("5,250", None, ["E1"], SOURCE) is None
    assert mod._ground_quote("Rows delivered: 5,250", None, ["E1"], SOURCE) == {
        "evidence_id": "E1", "text": "Rows delivered: 5,250"}
    assert len(SOURCE["E3"]) > mod.QUOTE_CAP        # it really is over the cap
    trimmed = mod._ground_quote(SOURCE["E3"], "E3", ["E3"], SOURCE)
    assert trimmed is not None and len(trimmed["text"]) <= mod.QUOTE_CAP
    assert grounds(mod, trimmed["text"], "E3", ("E3",))


def test_a_too_short_quote_is_dropped_not_fatal(guard, direct_vm, policy_id):
    """The gate refuses a stored quote under the minimum length, so the
    normalizer has to drop one before it is stored. Otherwise a model that
    quotes "5,250" beside a proper quote makes the leader's own payload fail
    its gate, and the round dies on every node."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": {"state": "SATISFIED", "note": "",
               "quotes": [{"evidence_id": "E1", "text": "5,250"},
                          {"evidence_id": "E1", "text": "Rows delivered: 5,250"}]},
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    }))
    c1 = finding(record, "C1")
    assert c1["state"] == "SATISFIED"
    assert [q["text"] for q in c1["quotes"]] == ["Rows delivered: 5,250"]


def test_the_cut_that_lost_a_live_quote(mod):
    """A StudioNet validator quoted the method report's first paragraph whole:
    300 characters over four lines, grounded as written. Cut to the cap it
    ended on one word after a line break, and the quote was dropped. It is
    now kept, cut at the last word that fits."""
    report = {"E2": file_bytes("sources/delivery/method-report.txt").decode()}
    paragraph = ("The enrichment ran in three passes. The first pass queried the "
                 "Geocodex v2\nendpoint for every row. The second pass re-queried rows "
                 "whose confidence was\nbelow 0.6, using the postal code rather than the "
                 "free-text address. The third\npass reconciled the two answers and kept "
                 "the higher-confidence result.")
    assert len(paragraph) > mod.QUOTE_CAP
    kept = mod._ground_quote(paragraph, "E2", ["E2"], report)
    assert kept is not None and len(kept["text"]) <= mod.QUOTE_CAP
    assert kept["text"].endswith("The third\npass")


@pytest.mark.parametrize("path", ["sources/delivery/method-report.txt",
                                  "sources/delivery/enriched-dataset-summary.txt",
                                  "sources/delivery/partial-dataset-summary.txt",
                                  "sources/logs/borealis-run-log.json"])
def test_cutting_to_the_cap_never_loses_a_quote_that_grounds(mod, path):
    """The property behind the live failure: whatever a model quotes, the
    cut to the cap is never what loses it. Verbatim runs of lines, lines
    joined from every other line, elisions and comma reflows, starting at
    every line and shifted a word at a time so the cap lands everywhere -
    each one that grounds as written is kept."""
    texts = {"E1": file_bytes(path).decode()}
    lines = [line for line in texts["E1"].split("\n") if line.strip()]
    checked = 0
    for start in range(len(lines)):
        for step in (1, 2):
            for joiner in ("\n", " ... ", ", "):
                picked = lines[start::step]
                words = picked[0].split()
                for skip in range(min(len(words) - 1, 12)):
                    quote = joiner.join([" ".join(words[skip:])] + picked[1:]).strip()
                    if len(quote) <= mod.QUOTE_CAP or not mod._quote_grounded(
                            {"evidence_id": "E1", "text": quote}, ["E1"], texts):
                        continue
                    kept = mod._ground_quote(quote, "E1", ["E1"], texts)
                    assert kept is not None, quote
                    assert len(kept["text"]) <= mod.QUOTE_CAP
                    checked += 1
    assert checked > 20            # the property was exercised, not vacuous


def test_an_answer_is_normalized_to_what_the_evidence_allows(mod):
    """A model may name a state that is not in the vocabulary, or evidence
    it was not shown. Neither survives normalization: an unknown state is no
    state at all, and only eligible ids are kept."""
    state, ids, quotes, note = mod._normalize_answer(
        {"state": "MAYBE", "evidence_ids": ["E1", "E9"],
         "quotes": [{"evidence_id": "E1", "text": "Rows delivered: 5,250"}],
         "note": "unsure"}, mod.CRITERION_STATES, ["E1"], SOURCE)
    assert state is None                    # not in the vocabulary
    assert ids == ["E1"] and note == "unsure"
    assert quotes == [{"evidence_id": "E1", "text": "Rows delivered: 5,250"}]
    state, ids, _quotes, _note = mod._normalize_answer(
        {"status": "satisfied"}, mod.CRITERION_STATES, ["E1"], SOURCE)
    assert state == "SATISFIED" and ids == []
    # ids a model lists out of the pool's order come back in it: the gate
    # refuses a finding whose ids are not, so the model's ordering would
    # otherwise sink the leader's own payload
    _state, ids, _quotes, _note = mod._normalize_answer(
        {"state": "SATISFIED", "evidence_ids": ["E2", "E1"]}, mod.CRITERION_STATES,
        ["E1", "E2"], SOURCE)
    assert ids == ["E1", "E2"]


def test_a_finding_may_not_rest_only_on_the_agent_it_favours(mod):
    """The party-interest rule, on its own: a finding that favours one agent
    needs at least one quoted item that agent did not write. Its own words
    are not support for its own case - but the other side's admission is."""
    parties = {"E1": "seller", "E5": "buyer"}
    seller_only = [{"evidence_id": "E1", "text": "we were blocked all week"}]
    buyer_word = [{"evidence_id": "E5", "text": "I will not issue the key"}]
    assert not mod._support_satisfies(1, "seller", seller_only, parties)
    assert mod._support_satisfies(1, "seller", buyer_word, parties)
    assert mod._support_satisfies(1, "seller", seller_only + buyer_word, parties)
    assert mod._support_satisfies(1, "", seller_only, parties)     # favours nobody
    assert not mod._support_satisfies(1, "seller", [], parties)    # no support at all


@pytest.mark.parametrize("reply", ["[1, 2]", "17", "\"the delivery looks fine\""])
def test_a_model_answer_that_is_not_an_object_is_not_an_answer(guard, direct_vm,
                                                               policy_id, reply):
    """A list, a number or prose where an answer belongs: the round records
    MODEL_OUTPUT_INVALID and holds, rather than reading it as an answer that
    happened to decide nothing."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, reply)
    assert record["panel_state"] == "MODEL_OUTPUT_INVALID"
    assert record["settleable"] is False


def test_the_gate_refuses_a_panel_state_code_did_not_reach(guard, direct_vm, mod,
                                                           policy_id):
    """Every item excluded by code leaves nothing for a panel to read, and
    the round says so. A leader claiming the panel answered would change only
    the record's account of how it decided - which is exactly why the gate
    recomputes it."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = commit(guard, direct_vm, agreement_id, [
        ("DELIVERABLE", "sources/delivery/injected-summary.txt", "Borealis",
         "the delivery summary")])
    from tests.direct.support import as_sender
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id)
    assert record["panel_reason"] == "NO_EXAMINED_EVIDENCE"
    assert record["panel_state"] == "SKIPPED"
    ctx = captured_ctx(direct_vm)
    texts = mod._node_round(ctx)[1]
    forged = copy.deepcopy(captured_payload(direct_vm))
    forged["panel_state"] = "ASSESSED"
    assert mod._parse_payload(mod._canonical(forged), ctx, texts) is None


def test_the_gate_refuses_findings_a_skipped_round_did_not_make(guard, direct_vm, mod,
                                                                policy_id):
    """When code skipped the panel, every finding in the payload is one code
    itself produced. A leader that rewrites one is proposing a reading nobody
    performed."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = commit(guard, direct_vm, agreement_id, [
        ("DELIVERABLE", "sources/delivery/injected-summary.txt", "Borealis",
         "the delivery summary")])
    from tests.direct.support import as_sender
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id)
    assert record["panel_state"] == "SKIPPED"
    ctx = captured_ctx(direct_vm)
    texts = mod._node_round(ctx)[1]
    honest = captured_payload(direct_vm)
    assert mod._parse_payload(mod._canonical(honest), ctx, texts) is not None
    forged = copy.deepcopy(honest)
    subject(forged, "C1")["state"] = "SATISFIED"
    assert mod._parse_payload(mod._canonical(forged), ctx, texts) is None


def test_equivalence_statement_is_published(guard, mod):
    """A reviewer can read the rule the validators actually apply, from the
    contract itself."""
    published = guard.get_config()["equivalence"]
    assert published == mod.EQUIVALENCE_STATEMENT
    assert "hash-verifying every allowed evidence item itself" in published
    assert "no model output reaches an amount" in published
