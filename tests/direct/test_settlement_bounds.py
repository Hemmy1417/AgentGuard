"""Settlement: the arithmetic between a verdict and the ledger. Every test
here asks the same question in a different way - can any path move more than
the escrow, less than the escrow, or move it twice?"""

from types import SimpleNamespace

import pytest

from tests.direct.support import (
    DELIVERY, FULL_ANSWER, PRICE, adjudicate, agreement, answer, as_sender, claimable,
    commit,
    deliver, dispute, finding, policy_definition, receipt, satisfied, setup,
    warp)

AFTER_APPEAL = "2026-09-16T12:00:01Z"
UNSTAMPED = ("DELIVERABLE", "sources/delivery/unstamped-dataset-summary.txt",
             "Borealis", "the catalogue dataset summary")


def settled(guard, direct_vm, policy_id, panel_answer, buyer_message=False, **terms):
    """Run one dispute to settlement and return the agreement view."""
    agreement_id = agreement(guard, direct_vm, policy_id, **terms)
    deliver(guard, direct_vm, agreement_id)
    if buyer_message:
        commit(guard, direct_vm, agreement_id, [
            ("AGENT_MESSAGE", "messages/atlas-withholds-access.txt", "Atlas",
             "the buyer's message")], "buyer")
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, panel_answer)
    if record["settleable"]:
        warp(direct_vm, AFTER_APPEAL)
        as_sender(direct_vm, "stranger")
        guard.finalize_settlement(agreement_id)
    return guard.get_agreement(agreement_id), record


# -- the mapping from a verdict to basis points ---------------------------------

def test_full_fulfillment_pays_everything(guard, direct_vm, policy_id):
    view, record = settled(guard, direct_vm, policy_id, FULL_ANSWER)
    assert record["seller_bps"] == 10000
    assert view["settled_seller_atto"] == str(PRICE)
    assert view["settled_buyer_atto"] == "0"


def test_partial_fulfillment_is_interpolated(guard, direct_vm, policy_id):
    """C1 satisfied (40) and C3 satisfied (20) of 90 counted weight is level
    66, two thirds of the way from the partial threshold to the full one, so
    the seller's share is the policy floor plus two thirds of the rest."""
    partial = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    })
    view, record = settled(guard, direct_vm, policy_id, partial)
    assert record["verdict"] == "PARTIALLY_FULFILLED"
    assert record["fulfillment_level"] == 66
    # 4000 + (10000-4000) * (66-40) // (90-40) = 4000 + 3120
    assert record["seller_bps"] == 7120
    assert int(view["settled_seller_atto"]) == PRICE * 7120 // 10000
    assert int(view["settled_seller_atto"]) + int(view["settled_buyer_atto"]) == PRICE


def test_nothing_satisfied_pays_nothing(guard, direct_vm, policy_id):
    none = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250", "NOT_SATISFIED"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes", "NOT_SATISFIED"),
    })
    view, record = settled(guard, direct_vm, policy_id, none)
    assert record["verdict"] == "NOT_FULFILLED" and record["seller_bps"] == 0
    assert view["settled_buyer_atto"] == str(PRICE)
    assert record["seller_fault_level"] == "FULL"
    assert record["confidence"] == "HIGH"          # every criterion was decided


def test_a_policy_may_pay_a_floor_on_a_failed_delivery(guard, direct_vm, policy_id):
    """not_fulfilled_seller_bps is the policy's, not the contract's: two
    agents may agree that a failed delivery still covers part of the seller's
    cost, and the demo policy's zero is a choice rather than a rule."""
    from tests.direct.support import policy_json
    as_sender(direct_vm, "platform")
    lenient = guard.register_policy(policy_json(not_fulfilled_seller_bps=1500))
    agreement_id = agreement(guard, direct_vm, lenient)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250", "NOT_SATISFIED"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes", "NOT_SATISFIED")}))
    assert record["verdict"] == "NOT_FULFILLED"
    assert record["seller_bps"] == 1500
    assert int(record["payment_allocation_atto"]) == PRICE * 1500 // 10000
    assert int(record["payment_allocation_atto"])         + int(record["refund_allocation_atto"]) == PRICE


def test_an_unverifiable_criterion_lowers_the_recorded_confidence(guard, direct_vm,
                                                                  policy_id):
    """A record says how sure it is: HIGH when every criterion was decided,
    MEDIUM when one could not be, LOW when no panel answered at all. A reader
    settling downstream needs that distinction more than the verdict."""
    partial = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
        "C3": {"state": "UNVERIFIABLE", "quotes": [], "note": "the report is silent"},
    })
    _view, record = settled(guard, direct_vm, policy_id, partial)
    assert finding(record, "C3")["state"] == "UNVERIFIABLE"
    assert record["confidence"] == "MEDIUM"


@pytest.mark.parametrize("indicator,quoted_from,verdict,bps,seller_fault,buyer_fault", [
    # a finding that favours one agent needs support that agent did not write:
    # E5 is the buyer's own message, E1 the seller's own summary
    ("BUYER_WITHHELD_INPUT", "E5", "BUYER_NON_COOPERATION", 7500, "NONE", "FULL"),
    ("EXTERNAL_DEPENDENCY_FAILED", "E5", "EXTERNAL_DEPENDENCY_FAILURE", 2500,
     "NONE", "NONE"),
    ("SELLER_SCOPE_CHANGE", "E1", "NOT_FULFILLED", 0, "FULL", "NONE"),
])
def test_fault_verdicts_take_their_policy_share(guard, direct_vm, policy_id, indicator,
                                                quoted_from, verdict, bps, seller_fault,
                                                buyer_fault):
    text = {"E5": "I am not going to issue the API key",
            "E1": "Columns added: geo_lat, geo_lon, admin_region"}[quoted_from]
    quoted = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    }, {indicator: {"state": "PRESENT",
                    "quotes": [{"evidence_id": quoted_from, "text": text}],
                    "note": "as quoted"}})
    view, record = settled(guard, direct_vm, policy_id, quoted, buyer_message=True)
    assert record["verdict"] == verdict and record["seller_bps"] == bps
    assert record["seller_fault_level"] == seller_fault
    assert record["buyer_fault_level"] == buyer_fault
    assert int(view["settled_seller_atto"]) == PRICE * bps // 10000
    assert int(view["settled_seller_atto"]) + int(view["settled_buyer_atto"]) == PRICE


def test_both_at_fault_splits_by_policy(guard, direct_vm, policy_id):
    both = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    }, {"BUYER_WITHHELD_INPUT": {"state": "PRESENT", "quotes": [
            {"evidence_id": "E5", "text": "I am not going to issue the API key"}],
            "note": ""},
        "SELLER_SCOPE_CHANGE": {"state": "PRESENT", "quotes": [
            {"evidence_id": "E2", "text": "The enrichment ran in three passes"}],
            "note": ""}})
    view, record = settled(guard, direct_vm, policy_id, both, buyer_message=True)
    assert record["verdict"] == "MUTUAL_FAULT" and record["seller_bps"] == 5000
    assert record["seller_fault_level"] == "PARTIAL"
    assert record["buyer_fault_level"] == "PARTIAL"
    assert int(view["settled_seller_atto"]) == PRICE // 2


@pytest.mark.parametrize("indicator,verdict,settles", [
    # deciding any of these could have moved the money, so an undecided
    # answer holds the escrow
    ("EVIDENCE_MANIPULATION", "INCONCLUSIVE", False),
    ("INSTRUCTION_INJECTION", "INCONCLUSIVE", False),
    ("BUYER_WITHHELD_INPUT", "INCONCLUSIVE", False),
    ("EXTERNAL_DEPENDENCY_FAILED", "INCONCLUSIVE", False),
    ("SELLER_SCOPE_CHANGE", "INCONCLUSIVE", False),
    # this one only records whether the buyer demanded more than the criteria.
    # It is fault, not money, and a delivery the panel found complete is paid
    ("BUYER_CRITERIA_CHANGE", "FULFILLED", True),
])
def test_an_undecided_question_holds_only_what_it_could_change(
        guard, direct_vm, policy_id, indicator, verdict, settles):
    """A live readjudication found every criterion satisfied at 100/100 and
    still paid nobody, because the panel had left one fault question
    undecided. An escrow may only be held by a question whose answer could
    have changed where it goes."""
    undecided = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    }, {indicator: {"state": "UNDETERMINED", "quotes": [], "note": "cannot tell"}})
    view, record = settled(guard, direct_vm, policy_id, undecided)
    assert record["fulfillment_level"] == 100
    assert record["verdict"] == verdict
    assert record["settleable"] is settles
    if settles:
        assert record["seller_bps"] == 10000
        assert view["settled_seller_atto"] == str(PRICE)
        assert record["buyer_fault_level"] == "NONE"   # unproven is not fault
    else:
        assert record["seller_bps"] == 0
        assert guard.health_check()["escrow_held_atto"] == str(PRICE)


# -- the bounds themselves --------------------------------------------------------

def test_allocations_always_reconcile_to_the_escrow(mod):
    """_split over the whole basis-point range and a deliberately awkward
    escrow: the two allocations sum to the escrow, exactly, every time."""
    for escrow in (1, 2, 3, 999, 10 ** 18 + 7, 400 * 10 ** 18, 10 ** 24 - 1):
        for bps in (0, 1, 3333, 4999, 5000, 7120, 9999, 10000):
            seller, buyer = mod._split(escrow, bps)
            assert seller >= 0 and buyer >= 0
            assert seller + buyer == escrow
            assert seller <= escrow


def test_the_remainder_goes_to_the_buyer(mod):
    """Integer division cannot round in the seller's favour: the wei that
    does not divide stays with the agent who paid it."""
    seller, buyer = mod._split(10 ** 18 + 1, 5000)
    assert seller == (10 ** 18 + 1) // 2
    assert buyer == seller + 1


def test_seller_bps_is_bounded_for_every_verdict(mod):
    """Every verdict, at every level: inside the escrow, and zero for every
    verdict the policy does not give a share of its own - a seller that never
    performed, a buyer's silence, and each of the four holds."""
    policy = policy_definition()
    pays_nothing = ("SELLER_NON_PERFORMANCE", "REJECTED", "INSUFFICIENT_EVIDENCE",
                    "CONFLICTING_EVIDENCE", "SOURCE_UNAVAILABLE", "INCONCLUSIVE",
                    "NOT_A_VERDICT")
    for verdict in ("FULFILLED", "PARTIALLY_FULFILLED", "NOT_FULFILLED",
                    "BUYER_NON_COOPERATION", "MUTUAL_FAULT",
                    "EXTERNAL_DEPENDENCY_FAILURE") + pays_nothing:
        for level in range(0, 101):
            bps = mod._seller_bps(policy, verdict, level)
            assert 0 <= bps <= 10000, (verdict, level, bps)
            if verdict in pays_nothing:
                assert bps == 0, (verdict, level, bps)


def test_partial_share_never_exceeds_a_full_one(mod):
    policy = policy_definition()
    previous = -1
    for level in range(policy["partial_threshold"], policy["full_threshold"] + 1):
        bps = mod._seller_bps(policy, "PARTIALLY_FULFILLED", level)
        assert bps >= previous            # more delivered is never worth less
        assert bps <= 10000
        previous = bps
    assert mod._seller_bps(policy, "PARTIALLY_FULFILLED",
                           policy["partial_threshold"]) == 4000


def settle_directly(mod, escrow: int, seller: int, buyer: int, total: int = None):
    """Call _settle with a stub agreement and a stub contract state. The
    method is the single door every settlement goes through, and its
    arithmetic is worth testing without a whole lifecycle around it."""
    state = SimpleNamespace(escrow_total_atto=total if total is not None else escrow,
                            credits={}, credits_total_atto=0)
    state._fail = mod.AgentGuard._fail.__get__(state)
    state._credit = mod.AgentGuard._credit.__get__(state)
    agreement = SimpleNamespace(
        escrow_atto=escrow, seller=mod.Address("0x" + "11" * 20),
        buyer=mod.Address("0x" + "22" * 20), settled_seller_atto=0,
        settled_buyer_atto=0, settlement_route="", status="ADJUDICATED",
        finalized_at="")
    mod.AgentGuard._settle.__get__(state)(agreement, seller, buyer, "TEST",
                                          "2026-09-13T12:00:00Z")
    return state, agreement


def test_settle_moves_the_escrow_whole_or_not_at_all(mod):
    state, agreement = settle_directly(mod, 100, 60, 40)
    assert int(agreement.escrow_atto) == 0 and agreement.status == "FINALIZED"
    assert int(state.escrow_total_atto) == 0
    assert sum(int(v) for v in state.credits.values()) == 100
    assert int(agreement.settled_seller_atto) == 60
    assert int(agreement.settled_buyer_atto) == 40


@pytest.mark.parametrize("escrow,seller,buyer,total,message", [
    (100, 60, 30, None, "reconcile"),          # less than the escrow
    (100, 60, 50, None, "reconcile"),          # more than the escrow
    (100, 101, -1, None, "negative"),          # a negative allocation
    (100, 60, 40, 50, "escrow accounting"),    # more escrow than the contract holds
])
def test_settle_refuses_anything_that_does_not_reconcile(mod, escrow, seller, buyer,
                                                         total, message):
    with pytest.raises(Exception) as err:
        settle_directly(mod, escrow, seller, buyer, total)
    assert message in str(err.value)


def test_a_holding_verdict_moves_nothing(guard, direct_vm, policy_id):
    """SOURCE_UNAVAILABLE holds: no allocation, no finalization, escrow
    untouched, and the contract says so rather than inventing fault."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    from tests.direct.support import DELIVERY, stage
    stage(direct_vm, FULL_ANSWER, skip=(DELIVERY[0][1],))
    as_sender(direct_vm, "stranger")
    record = guard.get_adjudication(guard.request_adjudication(agreement_id))
    assert record["verdict"] == "SOURCE_UNAVAILABLE"
    assert record["settleable"] is False
    assert record["payment_allocation_atto"] == "0"
    assert record["refund_allocation_atto"] == "0"
    assert "ESCROW_HELD" in record["reason_codes"]
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("does not settle"):
        guard.finalize_settlement(agreement_id)
    assert guard.health_check()["escrow_held_atto"] == str(PRICE)


def test_an_agreement_cannot_settle_twice(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    as_sender(direct_vm, "buyer")
    guard.accept_delivery(agreement_id)
    with direct_vm.expect_revert("agreement is FINALIZED"):
        guard.accept_delivery(agreement_id)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("agreement is FINALIZED"):
        guard.finalize_settlement(agreement_id)
    with direct_vm.expect_revert("not stalled"):
        guard.claim_stalled_agreement(agreement_id)
    assert claimable(guard, "seller") == PRICE     # still exactly one payment


def test_the_ledger_is_the_only_way_out(guard, direct_vm, policy_id):
    """Two agreements settle in opposite directions; each agent withdraws
    exactly what its verdicts credited, and the books balance. The second
    agreement reuses only the delivered artifacts - a seller may sell the
    same dataset twice - while its logs would belong to the first job."""
    first = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, first)
    as_sender(direct_vm, "buyer")
    guard.accept_delivery(first)

    second = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, second, items=[UNSTAMPED])
    dispute(guard, direct_vm, second)
    none = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250", "NOT_SATISFIED"),
        "C3": satisfied("E1", "the same file is sold to more than one buyer",
                        "NOT_SATISFIED"),
    })
    record = adjudicate(guard, direct_vm, second, none)
    assert record["verdict"] == "NOT_FULFILLED"
    assert finding(record, "C2")["state"] == "UNVERIFIABLE"   # no log of its own
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    guard.finalize_settlement(second)

    assert claimable(guard, "seller") == PRICE
    assert claimable(guard, "buyer") == PRICE
    assert guard.health_check()["escrow_held_atto"] == "0"
    assert int(guard.health_check()["claimable_atto"]) == 2 * PRICE
    as_sender(direct_vm, "seller")
    guard.withdraw()
    as_sender(direct_vm, "buyer")
    guard.withdraw()
    assert guard.health_check()["claimable_atto"] == "0"


def test_a_deliverable_sold_twice_is_not_reuse(guard, direct_vm, policy_id):
    """The registry catches recycled paperwork, not a second sale. An
    unstamped catalogue artifact delivered to a second buyer counts; the
    first job's log and receipt, which name that job, do not."""
    first = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, first, items=[UNSTAMPED] + list(DELIVERY[2:]))
    as_sender(direct_vm, "buyer")
    guard.accept_delivery(first)
    second = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, second, items=[UNSTAMPED] + list(DELIVERY[2:]))
    dispute(guard, direct_vm, second)
    record = adjudicate(guard, direct_vm, second, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C3": satisfied("E1", "the same file is sold to more than one buyer"),
    }))
    reuse = finding(record, "CROSS_AGREEMENT_REUSE")
    assert reuse["state"] == "PRESENT"
    assert set(reuse["evidence_ids"]) == {"E2", "E3"}      # the log and the receipt
    assert "E1" not in reuse["evidence_ids"]               # the artifact is clean
    assert receipt(record, "E1")["counted"] is True
    assert receipt(record, "E2")["counted"] is False
    assert record["verdict"] == "PARTIALLY_FULFILLED"


def test_a_stranger_cannot_withdraw_what_it_did_not_earn(guard, direct_vm, policy_id):
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    as_sender(direct_vm, "buyer")
    guard.accept_delivery(agreement_id)
    as_sender(direct_vm, "stranger")
    with direct_vm.expect_revert("nothing to withdraw"):
        guard.withdraw()
    as_sender(direct_vm, "buyer")
    with direct_vm.expect_revert("nothing to withdraw"):
        guard.withdraw()


def test_price_bounds(guard, direct_vm, policy_id):
    with direct_vm.expect_revert("price_atto must be an integer"):
        agreement(guard, direct_vm, policy_id, price_atto=0, fund=False)
    with direct_vm.expect_revert("price_atto must be an integer"):
        agreement(guard, direct_vm, policy_id, price_atto=10 ** 25, fund=False)
    with direct_vm.expect_revert("price_atto must be an integer"):
        agreement(guard, direct_vm, policy_id, price_atto=1.5, fund=False)
    small = agreement(guard, direct_vm, policy_id, price_atto=1)
    assert guard.get_agreement(small)["escrow_atto"] == "1"


def test_one_wei_still_reconciles(guard, direct_vm, policy_id):
    """The smallest possible escrow, split by a partial verdict: the seller
    gets nothing, the buyer gets the wei, and nothing is created."""
    agreement_id = agreement(guard, direct_vm, policy_id, price_atto=1)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    partial = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    })
    record = adjudicate(guard, direct_vm, agreement_id, partial)
    assert record["seller_bps"] == 7120
    warp(direct_vm, AFTER_APPEAL)
    as_sender(direct_vm, "stranger")
    guard.finalize_settlement(agreement_id)
    assert claimable(guard, "seller") == 0
    assert claimable(guard, "buyer") == 1
    assert guard.health_check()["escrow_held_atto"] == "0"


def test_escrow_survives_a_policy_change(guard, direct_vm, policy_id):
    """A live agreement keeps the policy version it froze: republishing the
    policy with a harsher split cannot reach into an escrow already funded."""
    agreement_id = agreement(guard, direct_vm, policy_id)
    deliver(guard, direct_vm, agreement_id)
    as_sender(direct_vm, "platform")
    from tests.direct.support import policy_json
    guard.publish_policy_version(policy_id, policy_json(buyer_non_cooperation_seller_bps=0))
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, FULL_ANSWER)
    assert guard.get_agreement(agreement_id)["policy_version"] == 1
    assert record["verdict"] == "FULFILLED" and record["seller_bps"] == 10000


@pytest.mark.parametrize("threshold,expected,bps", [
    ("full_threshold", "FULFILLED", 10000),
    ("partial_threshold", "PARTIALLY_FULFILLED", 4000),
])
def test_a_level_exactly_at_a_threshold_is_inside_it(guard, direct_vm, policy_id,
                                                     threshold, expected, bps):
    """Both thresholds are inclusive, and the boundary is where the money
    changes: a level of exactly 66 is fulfilled under a policy whose full
    threshold is 66, and partial rather than a breach under one whose partial
    threshold is 66."""
    from tests.direct.support import policy_json
    overrides = {threshold: 66}
    if threshold == "partial_threshold":
        overrides["full_threshold"] = 90
    as_sender(direct_vm, "platform")
    boundary = guard.register_policy(policy_json(**overrides))
    agreement_id = agreement(guard, direct_vm, boundary)
    deliver(guard, direct_vm, agreement_id)
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes")}))
    assert record["fulfillment_level"] == 66
    assert record["verdict"] == expected and record["seller_bps"] == bps


def test_a_policy_can_demand_corroboration_before_any_split(guard, direct_vm,
                                                            policy_id):
    """minimum_evidence_items is a floor under every settlement, and it is
    checked before the level is: two readable items that satisfy every
    criterion still hold the escrow under a policy that asks for three. How
    much evidence a split may rest on is the agents' choice, not a
    by-product of how convincing the little they brought happened to be."""
    from tests.direct.support import policy_json
    as_sender(direct_vm, "platform")
    strict = guard.register_policy(policy_json(minimum_evidence_items=3))
    agreement_id = agreement(guard, direct_vm, strict)
    deliver(guard, direct_vm, agreement_id, [DELIVERY[0], DELIVERY[2]])
    dispute(guard, direct_vm, agreement_id)
    record = adjudicate(guard, direct_vm, agreement_id, answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E2", "\"status\": \"SUCCEEDED\""),
        "C3": satisfied("E1", "enrichment used the Geocodex v2 endpoint")}))
    # every criterion the panel could reach is satisfied, and it still holds
    assert record["fulfillment_level"] == 100
    assert [f["state"] for f in record["criteria"]] == ["SATISFIED", "SATISFIED",
                                                        "SATISFIED", "NOT_APPLICABLE"]
    assert record["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert record["settleable"] is False and record["seller_bps"] == 0
    assert "EVIDENCE:E1:EXCLUDED" not in record["reason_codes"]   # nothing was tainted
    assert guard.health_check()["escrow_held_atto"] == str(PRICE)


def test_a_second_policy_maps_partials_differently(guard, direct_vm):
    """The mapping is the policy's, not the contract's: the same evidence
    under a stricter policy pays the seller less."""
    policy_id = setup(guard, direct_vm, partial_seller_bps_at_threshold=1000,
                      full_threshold=95)
    partial = answer({
        "C1": satisfied("E1", "Rows delivered: 5,250"),
        "C2": satisfied("E3", "\"status\": \"SUCCEEDED\"", "NOT_SATISFIED"),
        "C3": satisfied("E2", "The enrichment ran in three passes"),
    })
    _view, record = settled(guard, direct_vm, policy_id, partial)
    assert record["fulfillment_level"] == 66
    # 1000 + 9000 * 26 // 55
    assert record["seller_bps"] == 1000 + 9000 * 26 // 55
    assert record["seller_bps"] < 7120
