"""Appeals, readjudication and the terminal exits. The escrow is the thing
being argued over, so the questions are: can an appeal change what the money
does, can it be filed after its window, and can the escrow ever strand?"""

import pytest

from tests.direct.support import (
    FULL_ANSWER, PRICE, adjudicate, agreement, answer, as_sender, claimable,
    commit, deliver, dispute, satisfied, setup, stage, wallet,
    warp)

# C1 and C2 met, C3 (the method report, judged subjectively) not: 70 of the
# 90 counted weight, so the seller's share is partial and an appeal has
# something to argue about.
PARTIAL = answer({
    "C1": satisfied("E1", "Rows delivered: 5,250"),
    "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
    "C3": satisfied("E2", "The enrichment ran in three passes", "NOT_SATISFIED"),
})
APPEALED = answer({
    "C1": satisfied("E1", "Rows delivered: 5,250"),
    "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
    "C3": satisfied("E5", "We found no fabricated rows"),
})
AFTER_APPEAL = "2026-09-16T12:00:01Z"
VERIFIER = ("THIRD_PARTY_RECORD", "sources/thirdparty/verifier-note.txt",
            "Meridian Data Assurance", "an independent spot check")


def adjudicated(guard, direct_vm, policy_id, panel_answer=PARTIAL):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, panel_answer)
    return agreement_id, record


def test_an_appeal_reopens_the_same_escrow_under_the_same_terms(guard, direct_vm,
                                                                policy_id):
    """The seller appeals a partial with a third party's check. The
    readjudication reads the same frozen terms, the same policy version and
    the same escrow; the appealed record is untouched."""
    agreement_id, original = adjudicated(guard, direct_vm, policy_id)
    assert original["seller_bps"] == 8440
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, "seller")
    appeal_id = guard.submit_appeal(agreement_id, "The checker confirms the runs.",
                                    new_ids)
    appeal = guard.get_appeal(appeal_id)
    assert appeal["status"] == "OPEN" and appeal["appellant"] == wallet("seller")
    assert appeal["adjudication_id"] == original["adjudication_id"]

    warp(direct_vm, "2026-09-14T12:00:00Z")
    stage(direct_vm, APPEALED)
    as_sender(direct_vm, "stranger")            # hearing it is permissionless
    new_id = guard.request_readjudication(appeal_id)
    new = guard.get_adjudication(new_id)
    assert new["kind"] == "READJUDICATION"
    assert new["appeal_of"] == original["adjudication_id"]
    assert new["verdict"] == "FULFILLED" and new["seller_bps"] == 10000
    assert new["terms_hash"] == original["terms_hash"]
    assert new["escrow_atto"] == original["escrow_atto"]
    assert new["changes"]["seller_bps"] == [8440, 10000]
    assert new["changes"]["verdict"] == ["PARTIALLY_FULFILLED", "FULFILLED"]
    assert new["changes"]["added_evidence"] == new_ids
    assert "CRITERION:C3:SATISFIED" in new["changes"]["reason_codes_added"]
    assert "CRITERION:C3:NOT_SATISFIED" in new["changes"]["reason_codes_removed"]

    # the appealed record is exactly as it was
    assert guard.get_adjudication(original["adjudication_id"]) == original
    assert guard.get_appeal(appeal_id)["status"] == "HEARD"
    assert guard.get_latest_adjudication(agreement_id)["adjudication_id"] == new_id


def test_the_readjudication_is_what_settles(guard, direct_vm, policy_id):
    agreement_id, original = adjudicated(guard, direct_vm, policy_id)
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, "seller")
    appeal_id = guard.submit_appeal(agreement_id, "The checker confirms the runs.",
                                    new_ids)
    warp(direct_vm, "2026-09-14T12:00:00Z")
    stage(direct_vm, APPEALED)
    as_sender(direct_vm, "stranger")
    guard.request_readjudication(appeal_id)
    warp(direct_vm, "2026-09-17T12:00:01Z")     # the new window has closed too
    as_sender(direct_vm, "stranger")
    guard.finalize_settlement(agreement_id)
    assert claimable(guard, "seller") == PRICE
    assert claimable(guard, "buyer") == 0


def test_an_appeal_cannot_be_filed_after_its_window(guard, direct_vm, policy_id):
    agreement_id, _record = adjudicated(guard, direct_vm, policy_id)
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("appeal window has closed"):
        guard.submit_appeal(agreement_id, "too late", new_ids)
    warp(direct_vm, "2026-09-15T12:00:00Z")     # the last second is in
    assert guard.submit_appeal(agreement_id, "just in time", new_ids)


def test_an_appeal_cannot_be_used_to_settle_twice(guard, direct_vm, policy_id):
    """Once finalized, the money is on the ledger and there is nothing left
    to appeal."""
    agreement_id, _record = adjudicated(guard, direct_vm, policy_id)
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    guard.finalize_settlement(agreement_id)
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("agreement is FINALIZED"):
        guard.submit_appeal(agreement_id, "let me try again", new_ids)


@pytest.mark.parametrize("who,message", [
    ("stranger", "only a party to this agreement"),
])
def test_only_a_party_appeals(guard, direct_vm, policy_id, who, message):
    agreement_id, _record = adjudicated(guard, direct_vm, policy_id)
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, who)
    with direct_vm.expect_revert(message):
        guard.submit_appeal(agreement_id, "not mine", new_ids)


def test_an_appeal_needs_new_evidence_of_its_own(guard, direct_vm, policy_id):
    agreement_id, record = adjudicated(guard, direct_vm, policy_id)
    judged = [e["record_id"] for e in record["evidence"]]
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("1 to 4 new evidence items"):
        guard.submit_appeal(agreement_id, "nothing new", [])
    with direct_vm.expect_revert("must not be evidence the adjudication read"):
        guard.submit_appeal(agreement_id, "the same again", judged[:1])
    buyer_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "buyer")
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("may only add its own evidence"):
        guard.submit_appeal(agreement_id, "the counterparty's", buyer_ids)
    with direct_vm.expect_revert("reason is required"):
        guard.submit_appeal(agreement_id, "", buyer_ids)


def test_the_policy_bounds_how_many_appeals(guard, direct_vm, policy_id):
    agreement_id, _record = adjudicated(guard, direct_vm, policy_id)
    first = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, "seller")
    appeal_id = guard.submit_appeal(agreement_id, "the checker", first)
    warp(direct_vm, "2026-09-14T12:00:00Z")
    stage(direct_vm, PARTIAL)
    as_sender(direct_vm, "stranger")
    guard.request_readjudication(appeal_id)
    second = commit(guard, direct_vm, agreement_id, [
        ("USAGE_RECORD", "sources/usage/atlas-usage.json", "Atlas Platform",
         "the buyer's usage record")], "seller")
    as_sender(direct_vm, "seller")
    with direct_vm.expect_revert("used its appeals"):
        guard.submit_appeal(agreement_id, "and again", second)


def test_an_open_appeal_blocks_finalization(guard, direct_vm, policy_id):
    agreement_id, _record = adjudicated(guard, direct_vm, policy_id)
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, "seller")
    appeal_id = guard.submit_appeal(agreement_id, "the checker", new_ids)
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("an appeal is waiting to be heard"):
        guard.finalize_settlement(agreement_id)
    status = guard.settlement_status(agreement_id, AFTER_APPEAL)
    assert status["appeal_pending"] is True and status["can_finalize_now"] is False
    assert guard.get_appeal(appeal_id)["status"] == "OPEN"


def test_a_readjudication_cannot_be_heard_twice(guard, direct_vm, policy_id):
    agreement_id, _record = adjudicated(guard, direct_vm, policy_id)
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, "seller")
    appeal_id = guard.submit_appeal(agreement_id, "the checker", new_ids)
    warp(direct_vm, "2026-09-14T12:00:00Z")
    stage(direct_vm, PARTIAL)
    as_sender(direct_vm, "stranger")
    guard.request_readjudication(appeal_id)
    stage(direct_vm, PARTIAL)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("already been heard"):
        guard.request_readjudication(appeal_id)


# -- the terminal exits ------------------------------------------------------------

def test_no_delivery_by_the_deadline_refunds_the_buyer(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("seller still has time to deliver"):
        guard.claim_stalled_agreement(agreement_id)
    warp(direct_vm, "2026-09-21T12:00:01Z")     # deadline + cure + stall
    assert guard.claim_stalled_agreement(agreement_id) == "SELLER_NON_PERFORMANCE"
    assert claimable(guard, "buyer") == PRICE
    assert claimable(guard, "seller") == 0
    assert guard.get_agreement(agreement_id)["settlement_route"] == "NO_DELIVERY"


def test_buyer_silence_pays_the_seller_when_the_policy_says_so(guard, direct_vm,
                                                               policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("buyer still has time"):
        guard.claim_stalled_agreement(agreement_id)
    warp(direct_vm, "2026-09-21T12:00:01Z")     # delivered + dispute + stall
    assert guard.claim_stalled_agreement(agreement_id) == "FULFILLED"
    assert claimable(guard, "seller") == PRICE
    assert guard.get_agreement(agreement_id)["settlement_route"] == "BUYER_SILENCE"


def test_buyer_silence_refunds_when_the_policy_says_the_opposite(guard, direct_vm):
    policy_id = setup(guard, direct_vm, silence_is_acceptance=False)
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    warp(direct_vm, "2026-09-21T12:00:01Z")
    as_sender(direct_vm, "stranger")
    assert guard.claim_stalled_agreement(agreement_id) == "REJECTED"
    assert claimable(guard, "buyer") == PRICE
    assert claimable(guard, "seller") == 0


def test_a_dispute_nobody_adjudicates_refunds_the_buyer(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("adjudication can still be requested"):
        guard.claim_stalled_agreement(agreement_id)
    warp(direct_vm, "2026-09-18T12:00:01Z")     # disputed + stall
    assert guard.claim_stalled_agreement(agreement_id) == "INCONCLUSIVE"
    assert claimable(guard, "buyer") == PRICE
    assert guard.get_agreement(agreement_id)["settlement_route"] == "NO_ADJUDICATION"


def test_an_unsettleable_adjudication_returns_the_escrow_to_its_payer(guard, direct_vm,
                                                                      policy_id):
    """The documented terminal rule: when the evidence never settled the
    question, the escrow goes back to the agent who paid it rather than
    stranding or rewarding an unproven claim."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, {"not": "an answer"})
    assert record["verdict"] == "INCONCLUSIVE" and record["settleable"] is False
    warp(direct_vm, "2026-09-21T12:00:01Z")
    as_sender(direct_vm, "stranger")
    assert guard.claim_stalled_agreement(agreement_id) == "INCONCLUSIVE"
    assert claimable(guard, "buyer") == PRICE
    assert guard.get_agreement(agreement_id)["settlement_route"] == \
        "UNSETTLED_ADJUDICATION"


def test_a_settleable_adjudication_left_alone_still_settles(guard, direct_vm, policy_id):
    """The stalled path never contradicts a standing verdict: it applies it."""
    agreement_id, record = adjudicated(guard, direct_vm, policy_id, FULL_ANSWER)
    assert record["settleable"] is True
    warp(direct_vm, "2026-09-21T12:00:01Z")
    as_sender(direct_vm, "stranger")
    assert guard.claim_stalled_agreement(agreement_id) == "FULFILLED"
    assert claimable(guard, "seller") == PRICE
    assert guard.get_agreement(agreement_id)["settlement_route"] == "ADJUDICATED"


def test_an_adjudicated_agreement_is_not_stalled_until_both_windows_pass(
        guard, direct_vm, policy_id):
    """The stalled route is the last resort, not a shortcut past the appeal
    window: the appealing party gets its window and the stall window on top
    of it before anyone can end the matter."""
    agreement_id, _record = adjudicated(guard, direct_vm, policy_id, FULL_ANSWER)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("appeal window has not passed"):
        guard.claim_stalled_agreement(agreement_id)
    warp(direct_vm, AFTER_APPEAL)               # the appeal window alone is not enough
    with direct_vm.expect_revert("appeal window has not passed"):
        guard.claim_stalled_agreement(agreement_id)
    warp(direct_vm, "2026-09-21T12:00:01Z")
    assert guard.claim_stalled_agreement(agreement_id) == "FULFILLED"


def test_a_pending_appeal_blocks_the_stalled_route_too(guard, direct_vm, policy_id):
    """finalize_settlement refuses while an appeal waits; so does the stalled
    route, or a party could simply wait out the clock rather than answer the
    appeal it was served."""
    agreement_id, record = adjudicated(guard, direct_vm, policy_id, PARTIAL)
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, "seller")
    appeal_id = guard.submit_appeal(agreement_id, "An independent check.", new_ids)
    warp(direct_vm, "2026-09-21T12:00:01Z")
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("appeal is waiting to be heard"):
        guard.claim_stalled_agreement(agreement_id)
    stage(direct_vm, APPEALED)
    guard.request_readjudication(appeal_id)
    # the readjudication arms its own appeal window, so the clock starts again
    warp(direct_vm, "2026-09-28T12:00:02Z")
    as_sender(direct_vm, "stranger")
    assert guard.claim_stalled_agreement(agreement_id) == "FULFILLED"
    assert claimable(guard, "seller") == PRICE


def test_an_appeal_cannot_be_heard_after_the_escrow_has_gone(guard, direct_vm,
                                                             policy_id):
    """An unsettleable adjudication with an open appeal can still be claimed
    as stalled - the escrow returns to the buyer. What must not happen next
    is a readjudication of an agreement that no longer holds anything."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    adjudicate(guard, direct_vm, agreement_id, {"not": "an answer"})
    new_ids = commit(guard, direct_vm, agreement_id, [VERIFIER], "seller")
    as_sender(direct_vm, "seller")
    appeal_id = guard.submit_appeal(agreement_id, "An independent check.", new_ids)
    warp(direct_vm, "2026-09-21T12:00:01Z")
    as_sender(direct_vm, "stranger")
    assert guard.claim_stalled_agreement(agreement_id) == "INCONCLUSIVE"
    assert claimable(guard, "buyer") == PRICE
    stage(direct_vm, APPEALED)
    with direct_vm.expect_revert("agreement is FINALIZED"):
        guard.request_readjudication(appeal_id)
    assert guard.health_check()["escrow_held_atto"] == "0"


def test_every_state_has_an_exit(guard, direct_vm, policy_id):
    """For each state an escrow can rest in, name who can move it and by
    when. None of these needs the counterparty's cooperation."""
    routes = {
        "FUNDED": ("2026-09-21T12:00:01Z", "SELLER_NON_PERFORMANCE"),
        "DELIVERED": ("2026-09-21T12:00:01Z", "FULFILLED"),
        "DISPUTED": ("2026-09-18T12:00:01Z", "INCONCLUSIVE"),
    }
    for state, (when, verdict) in routes.items():
        agreement_id = agreement(guard, direct_vm, policy_id)
        if state in ("DELIVERED", "DISPUTED"):
            deliver(guard, direct_vm, agreement_id)
        if state == "DISPUTED":
            dispute(guard, direct_vm, agreement_id)
        warp(direct_vm, when)
        as_sender(direct_vm, "stranger")        # a stranger can always unstick it
        assert guard.claim_stalled_agreement(agreement_id) == verdict
        assert guard.get_agreement(agreement_id)["status"] == "FINALIZED"
        warp(direct_vm, "2026-09-13T12:00:00Z")
    assert guard.health_check()["escrow_held_atto"] == "0"


def test_a_revoked_policy_does_not_strand_a_live_escrow(guard, direct_vm, policy_id):
    """Revoking a policy version stops new agreements binding it; the ones
    that already did still settle."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    as_sender(direct_vm, "platform")
    guard.revoke_policy_version(policy_id, 1)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, FULL_ANSWER)
    assert record["verdict"] == "FULFILLED"
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    guard.finalize_settlement(agreement_id)
    assert claimable(guard, "seller") == PRICE
