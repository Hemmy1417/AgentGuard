"""Evidence: admission, provenance frozen at assent, retrieval, the facts code
reads, and every way an item can be excluded from counting."""

import json

import pytest

from tests.direct.support import (
    BASE, DELIVERY, FULL_ANSWER, PRICE, adjudicate, agreement, answer, as_sender, commit,
    deliver, dispute, file_bytes, finding, item_sha, present, receipt, satisfied,
    serve_all, serve_bytes, sha256_hex, stage, terms_definition, url_of)

GOOD = DELIVERY[0]


def submit(guard, direct_vm, agreement_id, **changes):
    args = {"category": GOOD[0], "url": url_of(GOOD[1]), "sha256": item_sha(GOOD[1]),
            "issuer": GOOD[2], "description": GOOD[3]}
    args.update(changes)
    as_sender(direct_vm, changes.pop("party", "seller"))
    return guard.submit_evidence(agreement_id, args["category"], args["url"],
                                 args["sha256"], args["issuer"], args["description"])


# -- admission ------------------------------------------------------------------

@pytest.mark.parametrize("url,message", [
    ("http://evidence.example.org/a.json", "must use https"),
    ("https://user:pw@evidence.example.org/a.json", "credentials"),
    ("https://evidence.example.org:8443/a.json", "port"),
    ("https://10.0.0.5/a.json", "IP literal"),
    ("https://localhost/a.json", "localhost"),
    ("https://runner.internal/a.json", "internal"),
    ("https://evidence.example.org/a.json#frag", "fragment"),
    ("https://evidence.example.org/a\\b.json", "backslashes"),
    ("https://evidence.example.org/%2e%2e/a.json", "encode"),
    ("https://evidence.example.org/x/../a.json", "dot-segments"),
    ("https://evidence.example.org//a.json", "empty segments"),
    ("https://evidence.example.org/" + "a" * 300, "exceeds"),
    ("", "required"),
])
def test_url_admission(guard, direct_vm, policy_id, url, message):
    agreement_id = agreement(guard, direct_vm, policy_id)
    with direct_vm.expect_revert(message):
        submit(guard, direct_vm, agreement_id, url=url)


@pytest.mark.parametrize("changes,message", [
    ({"category": "SCREENSHOT"}, "category must be one of"),
    ({"sha256": "abc"}, "sha256 must be 64"),
    ({"sha256": "A" * 64}, "sha256 must be 64"),
    ({"issuer": ""}, "issuer is required"),
    ({"description": "x" * 500}, "description exceeds"),
    ({"description": "line\x07bell"}, "control characters"),
])
def test_field_admission(guard, direct_vm, policy_id, changes, message):
    agreement_id = agreement(guard, direct_vm, policy_id)
    with direct_vm.expect_revert(message):
        submit(guard, direct_vm, agreement_id, **changes)


def test_only_a_party_commits_evidence(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("only a party to this agreement"):
        guard.submit_evidence(agreement_id, GOOD[0], url_of(GOOD[1]), item_sha(GOOD[1]),
                              GOOD[2], GOOD[3])


def test_the_same_bytes_or_location_twice_is_refused(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    submit(guard, direct_vm, agreement_id)
    with direct_vm.expect_revert("already committed to this agreement"):
        submit(guard, direct_vm, agreement_id)
    with direct_vm.expect_revert("location is already committed"):
        submit(guard, direct_vm, agreement_id, sha256="b" * 64)
    with direct_vm.expect_revert("these exact bytes are already committed"):
        submit(guard, direct_vm, agreement_id,
               url=BASE + "sources/delivery/elsewhere.txt")


def test_the_evidence_list_is_bounded(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    for i in range(14):
        submit(guard, direct_vm, agreement_id,
               url=BASE + "sources/delivery/item-%d.txt" % i, sha256="%064x" % (i + 1))
    with direct_vm.expect_revert("already holds 14 evidence items"):
        submit(guard, direct_vm, agreement_id,
               url=BASE + "sources/delivery/item-99.txt", sha256="%064x" % 99)


# -- provenance frozen at assent ---------------------------------------------------

def test_a_source_outside_the_frozen_prefixes_is_not_fetched(guard, direct_vm, policy_id):
    """The impostor file is byte-identical to the real receipt, but it does
    not sit under the prefix the two agents froze."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = commit(guard, direct_vm, agreement_id, [
        DELIVERY[0],
        ("API_RECEIPT", "impostor/geocodex-official-receipt.json", "Geocodex",
         "the upstream receipt")])
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250")}))
    impostor = receipt(record, "E2")
    assert impostor["allowed"] is False and impostor["trusted"] is False
    assert impostor["status"] == "NOT_ALLOWED"
    assert impostor["retrieved_at"] == "" and impostor["counted"] is False
    assert finding(record, "C2")["state"] == "UNVERIFIABLE"
    assert finding(record, "C2")["by"] == "CODE"        # never asked, never guessed


def test_provenance_is_per_category(mod, policy_id):
    terms = terms_definition()
    log = BASE + "sources/logs/x.json"
    delivery = BASE + "sources/delivery/x.txt"
    assert mod._provenance(terms, "EXECUTION_LOG", log)[:2] == (True, True)
    assert mod._provenance(terms, "DELIVERABLE", log)[:2] == (False, False)
    assert mod._provenance(terms, "DELIVERABLE", delivery)[:2] == (True, True)
    # a lookalike folder beside the frozen one is not the frozen one
    assert mod._provenance(terms, "EXECUTION_LOG",
                           BASE + "sources/logs-verified/x.json")[:2] == (False, False)
    # an agent's own message is allowed from anywhere and never trusted
    assert mod._provenance(terms, "AGENT_MESSAGE",
                           "https://notes.example.net/m.txt")[:2] == (True, False)
    # a category the agreement does not source at all is admissible from
    # nowhere: the list of sources was frozen at assent, and it is not on it
    narrow = terms_definition()
    narrow["evidence_sources"] = [r for r in narrow["evidence_sources"]
                                  if r["category"] != "USAGE_RECORD"]
    usage = BASE + "sources/usage/x.json"
    assert mod._provenance(terms, "USAGE_RECORD", usage)[:2] == (True, True)
    assert mod._provenance(narrow, "USAGE_RECORD", usage)[:2] == (False, False)


# -- retrieval ---------------------------------------------------------------------

def test_an_unreachable_item_holds_the_escrow(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    stage(direct_vm, FULL_ANSWER, skip=(DELIVERY[2][1],))
    as_sender(direct_vm, "stranger")
    record = guard.get_adjudication(guard.request_adjudication(agreement_id))
    assert record["verdict"] == "SOURCE_UNAVAILABLE" and record["settleable"] is False
    assert receipt(record, "E3")["source_reachable"] is False
    assert record["panel_reason"] == "EVIDENCE_NOT_EXAMINED"
    # an item nobody could read is not an item that showed nothing: while one
    # is unread, the scans over the set are UNDETERMINED rather than ABSENT
    assert finding(record, "HIDDEN_TEXT")["state"] == "UNDETERMINED"
    assert finding(record, "INJECTION_MARKER")["state"] == "UNDETERMINED"
    assert finding(record, "DUPLICATE_EVIDENCE")["state"] == "UNDETERMINED"


def test_changed_bytes_are_never_read(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    direct_vm.clear_mocks()
    serve_bytes(direct_vm, url_of(DELIVERY[0][1]), b"a different summary entirely")
    serve_all(direct_vm)
    as_sender(direct_vm, "stranger")
    record = guard.get_adjudication(guard.request_adjudication(agreement_id))
    assert record["rows"][0] == {"evidence_id": "E1", "status": "HASH_MISMATCH",
                                 "byte_count": 0}
    assert record["verdict"] == "SOURCE_UNAVAILABLE"
    assert receipt(record, "E1")["hash_verified"] is False


@pytest.mark.parametrize("body,status,row", [
    (b"x" * 8001, 200, "TOO_LARGE"),
    (b"\xff\xfe not utf-8", 200, "UNPARSEABLE"),
    (b"   \n", 200, "UNPARSEABLE"),
    (b"{}", 200, "UNPARSEABLE"),
    (b"server exploded", 503, "UNAVAILABLE"),
])
def test_unreadable_items(guard, direct_vm, policy_id, body, status, row):
    agreement_id = agreement(guard, direct_vm, policy_id)
    url = BASE + "sources/logs/odd.json"
    ids = commit(guard, direct_vm, agreement_id, [DELIVERY[0]])
    as_sender(direct_vm, "seller")
    ids.append(guard.submit_evidence(agreement_id, "EXECUTION_LOG", url,
                                     sha256_hex(body), "Runner Cloud", "the run log"))
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    direct_vm.clear_mocks()
    serve_bytes(direct_vm, url, body, status)
    serve_all(direct_vm)
    as_sender(direct_vm, "stranger")
    record = guard.get_adjudication(guard.request_adjudication(agreement_id))
    assert record["rows"][1]["status"] == row
    assert record["settleable"] is False        # every one of these holds the escrow


@pytest.mark.parametrize("body,row", [(b"x" * 8001, "TOO_LARGE"),
                                      (b"\xff\xfe not utf-8", "UNPARSEABLE"),
                                      (b"   \n\t  \n", "UNPARSEABLE")])
def test_an_item_that_could_not_be_read_is_not_an_absent_item(guard, direct_vm,
                                                              policy_id, body, row):
    """INCONCLUSIVE, not INSUFFICIENT_EVIDENCE. The seller did deliver
    something and the contract could not read it - a different fact about the
    round, and a different thing for the seller to fix."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    url = BASE + "sources/delivery/odd-summary.txt"
    as_sender(direct_vm, "seller")
    eid = guard.submit_evidence(agreement_id, "DELIVERABLE", url, sha256_hex(body),
                                "Borealis", "the delivery summary")
    guard.submit_delivery(agreement_id, [eid], "delivered")
    dispute(guard, direct_vm, agreement_id)
    direct_vm.clear_mocks()
    serve_bytes(direct_vm, url, body)
    as_sender(direct_vm, "stranger")
    record = guard.get_adjudication(guard.request_adjudication(agreement_id))
    assert record["rows"] == [{"evidence_id": "E1", "status": row,
                               "byte_count": len(body)}]
    assert record["verdict"] == "INCONCLUSIVE" and record["settleable"] is False
    assert guard.health_check()["escrow_held_atto"] == str(PRICE)


# -- the facts code reads -----------------------------------------------------------

def test_the_parser_reads_integers_only(mod):
    good = file_bytes("sources/logs/borealis-run-log.json").decode()
    facts = mod._structured_facts(good, "EXECUTION_LOG", "E1")
    # 41 + 38 + 44 minutes of running, from the log's own timestamps: the
    # panel cannot weigh a claimed volume without the time it took
    assert facts["values"] == {"runs": 3, "succeeded": 3, "failed": 0, "items": 5250,
                               "elapsed_seconds": (41 + 38 + 44) * 60}
    assert facts["agreement_id"] == "AG-000001"
    bad = file_bytes("sources/logs/numeric-abuse-log.json").decode()
    assert mod._structured_facts(bad, "EXECUTION_LOG", "E1") is None
    reversed_time = file_bytes("sources/logs/fabricated-log.json").decode()
    assert mod._structured_facts(reversed_time, "EXECUTION_LOG", "E1") is None
    # the document says what it is; a log submitted as a receipt is neither
    assert mod._structured_facts(good, "API_RECEIPT", "E1") is None
    receipt_text = file_bytes("sources/receipts/geocodex-receipt.json").decode()
    assert mod._structured_facts(receipt_text, "EXECUTION_LOG", "E1") is None
    assert mod._structured_facts(receipt_text, "API_RECEIPT", "E1")["values"] == {
        "status_code": 200, "billed_units": 5250}


def test_a_boolean_is_not_a_number(mod):
    """True is 1 in Python and a lie in a log. Every integer the contract
    reads goes through _is_int, which refuses the bool subclass outright."""
    assert mod._is_int(5) and mod._is_int(0) and mod._is_int(-3)
    assert not mod._is_int(True) and not mod._is_int(False)
    assert not mod._is_int(1.0) and not mod._is_int("1") and not mod._is_int(None)
    assert mod._int_in(5, 0, 10) and not mod._int_in(True, 0, 10)


@pytest.mark.parametrize("changes", [
    {"total": 48, "passed": 40},                       # passed + failed != total
    {"total": -1}, {"total": 1.5}, {"total": True}, {"total": "48"},
])
def test_the_parser_rejects_impossible_totals(mod, changes):
    doc = json.loads(file_bytes("sources/tests/borealis-tests.json"))
    doc.update(changes)
    assert mod._structured_facts(json.dumps(doc), "TEST_OUTPUT", "E1") is None


def test_a_receipt_must_name_its_endpoint_and_request(mod):
    doc = json.loads(file_bytes("sources/receipts/geocodex-receipt.json"))
    assert mod._structured_facts(json.dumps(doc), "API_RECEIPT", "E1") is not None
    for key in ("endpoint", "request_id", "status_code"):
        broken = dict(doc)
        del broken[key]
        assert mod._structured_facts(json.dumps(broken), "API_RECEIPT", "E1") is None


# -- excluded from counting -----------------------------------------------------------

def test_a_log_naming_another_agreement_is_excluded(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = commit(guard, direct_vm, agreement_id, [
        DELIVERY[0],
        ("EXECUTION_LOG", "sources/logs/other-agreement-log.json", "Runner Cloud",
         "the run log")])
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250")}))
    unlinked = finding(record, "EVIDENCE_UNLINKED")
    assert unlinked["state"] == "PRESENT" and unlinked["evidence_ids"] == ["E2"]
    assert receipt(record, "E2")["counted"] is False
    assert receipt(record, "E2")["relevance_status"] == "OTHER_AGREEMENT"
    assert finding(record, "C2")["state"] == "UNVERIFIABLE"


def test_stale_evidence_cannot_show_current_delivery(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = commit(guard, direct_vm, agreement_id, [
        DELIVERY[0],
        ("EXECUTION_LOG", "sources/logs/stale-log.json", "Runner Cloud",
         "the run log")])
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250")}))
    assert "STALE_EVIDENCE" in present(record)
    assert receipt(record, "E2")["counted"] is False


def test_the_same_bytes_at_two_locations_are_refused_at_the_door(guard, direct_vm,
                                                                 policy_id):
    """A duplicate cannot make one delivery look like two. On this path the
    contract refuses the second commitment outright; the DUPLICATE_EVIDENCE
    indicator covers the adversarial-case engine, where a whole bundle
    arrives at once (test_adversarial_cases.py)."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    commit(guard, direct_vm, agreement_id, [DELIVERY[0]])
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("these exact bytes are already committed"):
        guard.submit_evidence(agreement_id, "DELIVERABLE",
                              url_of("sources/delivery/enriched-dataset-summary-copy.txt"),
                              item_sha("sources/delivery/enriched-dataset-summary.txt"),
                              "Borealis", "the same summary again")
    as_sender(direct_vm, "buyer")
    with direct_vm.expect_revert("these exact bytes are already committed"):
        guard.submit_evidence(agreement_id, "DELIVERABLE",
                              url_of("sources/delivery/enriched-dataset-summary-copy.txt"),
                              item_sha("sources/delivery/enriched-dataset-summary.txt"),
                              "Borealis", "the counterparty's copy")


def test_an_item_the_panel_never_saw_cannot_support_a_finding(guard, direct_vm,
                                                              policy_id):
    """A quote from an excluded item does not ground, so the criterion it was
    meant to satisfy falls back to UNVERIFIABLE."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    ids = commit(guard, direct_vm, agreement_id, [
        DELIVERY[0],
        ("EXECUTION_LOG", "sources/logs/other-agreement-log.json", "Runner Cloud",
         "the run log")])
    as_sender(direct_vm, "seller")
    guard.submit_delivery(agreement_id, ids, "delivered")
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E2", "\"status\": \"SUCCEEDED\""),
    }))
    assert finding(record, "C2")["state"] == "UNVERIFIABLE"


def test_evidence_may_be_added_while_a_dispute_is_open(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    ids = commit(guard, direct_vm, agreement_id, [
        ("THIRD_PARTY_RECORD", "sources/thirdparty/verifier-note.txt",
         "Meridian Data Assurance", "an independent spot check")], "buyer")
    assert ids == ["EV-000005"]
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
        "C3": satisfied("E5", "We found no fabricated rows"),
        "C4": satisfied("E5", "We sampled 200 rows of the delivered dataset"),
    }))
    assert record["verdict"] == "FULFILLED"
    assert receipt(record, "E5")["submitted_by"] == "buyer"
    assert finding(record, "C4")["state"] == "SATISFIED"      # optional, and met
