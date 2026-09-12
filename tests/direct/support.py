"""Shared scenario data and mock helpers for the Direct Mode suite.

The suite runs the real contract inside the official genlayer-test direct
runner (SDK resolved from the contract's own pinned runner hash). Only the
two external boundaries are mocked, and narrowly:

- web fetches: every file under fixtures/ is served at BASE + its relative
  path, byte for byte (an unmocked URL is unreachable, so the contract
  records the item UNAVAILABLE);
- the one panel prompt, matched on its header, answered with a JSON object.

Nothing in the contract is patched. Every verdict, every basis point and
every wei in this suite is produced by the contract's own code from those two
inputs.
"""

import copy
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = "contracts/agentguard.py"
MODULE = "_contract_agentguard"
FIXTURES = ROOT / "fixtures"

BASE = "https://evidence.example.org/agentguard/"
NOW = "2026-09-13T12:00:00Z"
DEADLINE = "2026-09-15T12:00:00Z"
PANEL_PATTERN = r"(?s)AgentGuard commerce panel"
GEN = 10 ** 18
PRICE = 400 * GEN

WALLETS = json.loads((FIXTURES / "wallets.json").read_text(encoding="utf-8"))
FOLDER = {"DELIVERABLE": "delivery", "EXECUTION_LOG": "logs", "API_RECEIPT": "receipts",
          "TEST_OUTPUT": "tests", "USAGE_RECORD": "usage",
          "THIRD_PARTY_RECORD": "thirdparty", "ACCEPTANCE_MESSAGE": "inbox"}


def wallet(name: str) -> str:
    return WALLETS[name]


def addr(name: str) -> bytes:
    return bytes.fromhex(WALLETS[name][2:])


def as_sender(direct_vm, name: str):
    direct_vm.sender = addr(name)


def file_bytes(rel: str) -> bytes:
    return (FIXTURES / rel).read_bytes()


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def item_sha(rel: str) -> str:
    return sha256_hex(file_bytes(rel))


def url_of(rel: str, base: str = BASE) -> str:
    return base + rel


# -- the settlement policy and the agreement ---------------------------------

def policy_definition(**overrides) -> dict:
    policy = {
        "name": "AgentGuard demo policy - data services",
        "full_threshold": 90,
        "partial_threshold": 40,
        "partial_seller_bps_at_threshold": 4000,
        "not_fulfilled_seller_bps": 0,
        "buyer_non_cooperation_seller_bps": 7500,
        "mutual_fault_seller_bps": 5000,
        "external_failure_seller_bps": 2500,
        "minimum_evidence_items": 1,
        "maximum_evidence_age_days": 30,
        "unverifiable_weight_limit": 40,
        "silence_is_acceptance": True,
        "maximum_appeals": 1,
    }
    policy.update(overrides)
    return policy


def policy_json(**overrides) -> str:
    return json.dumps(policy_definition(**overrides))


CRITERIA = [
    {"criterion_id": "C1", "kind": "OBJECTIVE", "weight": 40,
     "text": "At least 5,000 rows are delivered, enriched with geo_lat, geo_lon and "
             "admin_region, in a delimited file the buyer can load.",
     "evidence_categories": ["DELIVERABLE", "EXECUTION_LOG"],
     "requires_buyer_input": False, "external_dependency": ""},
    {"criterion_id": "C2", "kind": "OBJECTIVE", "weight": 30,
     "text": "The enrichment runs completed successfully against the Geocodex v2 "
             "endpoint, and the run log shows no failed or timed-out run.",
     "evidence_categories": ["EXECUTION_LOG", "API_RECEIPT"],
     "requires_buyer_input": False, "external_dependency": "Geocodex v2 endpoint"},
    {"criterion_id": "C3", "kind": "SUBJECTIVE", "weight": 20,
     "text": "A method report explains how the enrichment was produced and states "
             "its limitations honestly.",
     "evidence_categories": ["DELIVERABLE", "THIRD_PARTY_RECORD"],
     "requires_buyer_input": False, "external_dependency": ""},
    {"criterion_id": "C4", "kind": "OPTIONAL", "weight": 10,
     "text": "An independent spot check of the delivered rows is included.",
     "evidence_categories": ["THIRD_PARTY_RECORD"],
     "requires_buyer_input": False, "external_dependency": ""},
]


def terms_definition(policy_id: str = "SP-000001", base: str = BASE, **overrides) -> dict:
    terms = {
        "service_description":
            "Enrich the buyer's 5,000-row address dataset with geocoordinates and "
            "administrative regions using the Geocodex v2 endpoint, and deliver the "
            "enriched dataset with a method report.",
        "deliverables": ["the enriched dataset as a delimited file",
                         "a method report describing the enrichment and its limits"],
        "acceptance_criteria": copy.deepcopy(CRITERIA),
        "price_atto": PRICE,
        "deadline": DEADLINE,
        "cure_period_seconds": 86400,
        "dispute_window_seconds": 3 * 86400,
        "appeal_window_seconds": 2 * 86400,
        "stall_window_seconds": 5 * 86400,
        "evidence_sources": [
            {"category": category, "trusted_prefixes": [base + "sources/" + folder + "/"]}
            for category, folder in FOLDER.items()
        ] + [{"category": "AGENT_MESSAGE", "trusted_prefixes": []}],
        "external_dependencies": ["Geocodex v2 endpoint"],
        "policy_id": policy_id,
    }
    terms.update(overrides)
    return terms


def terms_json(policy_id: str = "SP-000001", base: str = BASE, **overrides) -> str:
    return json.dumps(terms_definition(policy_id, base, **overrides))


# -- mocks --------------------------------------------------------------------

def serve_all(direct_vm, base: str = BASE, skip=()):
    """Serve every fixture file at base + relative path (exact bytes)."""
    for path in sorted(FIXTURES.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(FIXTURES).as_posix()
        if rel in skip:
            continue
        direct_vm.mock_web("^" + re.escape(base + rel) + "$", {
            "method": "GET",
            "response": {"status": 200, "headers": {}, "body": path.read_bytes()}})


def serve_bytes(direct_vm, url: str, body: bytes, status: int = 200):
    direct_vm.mock_web("^" + re.escape(url) + "$", {
        "method": "GET", "response": {"status": status, "headers": {}, "body": body}})


def mock_panel(direct_vm, answer):
    direct_vm.mock_llm(PANEL_PATTERN,
                       answer if isinstance(answer, str) else json.dumps(answer))


def stage(direct_vm, answer=None, base: str = BASE, skip=()):
    direct_vm.clear_mocks()
    serve_all(direct_vm, base, skip)
    if answer is not None:
        mock_panel(direct_vm, answer)


def answer(criteria: dict, indicators: dict = None, absent=True) -> dict:
    """A panel answer: the criteria named, and every indicator ABSENT unless
    the caller says otherwise."""
    out = {"criteria": criteria, "indicators": {}}
    names = ("EVIDENCE_MANIPULATION", "BUYER_WITHHELD_INPUT",
             "EXTERNAL_DEPENDENCY_FAILED", "SELLER_SCOPE_CHANGE",
             "BUYER_CRITERIA_CHANGE", "INSTRUCTION_INJECTION")
    if absent:
        for name in names:
            out["indicators"][name] = {"state": "ABSENT", "quotes": [], "note": ""}
    out["indicators"].update(indicators or {})
    return out


def satisfied(evidence_id: str, quote: str, state: str = "SATISFIED") -> dict:
    return {"state": state, "quotes": [{"evidence_id": evidence_id, "text": quote}],
            "note": ""}


# The delivery the honest scenario submits, in commitment order.
DELIVERY = [
    ("DELIVERABLE", "sources/delivery/enriched-dataset-summary.txt", "Borealis",
     "the enriched dataset summary"),
    ("DELIVERABLE", "sources/delivery/method-report.txt", "Borealis",
     "the method report"),
    ("EXECUTION_LOG", "sources/logs/borealis-run-log.json", "Runner Cloud",
     "the run log"),
    ("API_RECEIPT", "sources/receipts/geocodex-receipt.json", "Geocodex",
     "the upstream receipt"),
]
FULL_ANSWER = answer({
    "C1": satisfied("E1", "Rows delivered: 5,250"),
    "C2": satisfied("E3", "\"status\": \"SUCCEEDED\""),
    "C3": satisfied("E2", "The enrichment ran in three passes"),
})


# -- flows --------------------------------------------------------------------

def setup(contract, direct_vm, base: str = BASE, **policy_overrides) -> str:
    """Register both agents and a settlement policy; returns the policy id."""
    for name in ("buyer", "seller"):
        as_sender(direct_vm, name)
        contract.register_agent(json.dumps(["dataset enrichment", "geocoding"]))
    as_sender(direct_vm, "platform")
    return contract.register_policy(policy_json(**policy_overrides))


def agreement(contract, direct_vm, policy_id: str = "SP-000001", base: str = BASE,
              fund: bool = True, **term_overrides) -> str:
    """Propose, accept and (by default) fund one agreement."""
    as_sender(direct_vm, "buyer")
    agreement_id = contract.propose_agreement(wallet("seller"),
                                              terms_json(policy_id, base,
                                                         **term_overrides))
    as_sender(direct_vm, "seller")
    contract.accept_agreement(agreement_id)
    if fund:
        as_sender(direct_vm, "buyer")
        direct_vm.value = term_overrides.get("price_atto", PRICE)
        contract.fund_escrow(agreement_id)
        direct_vm.value = 0
    return agreement_id


def commit(contract, direct_vm, agreement_id: str, items, party: str = "seller",
           base: str = BASE) -> list:
    """Commit evidence items as one party; returns the evidence ids."""
    as_sender(direct_vm, party)
    ids = []
    for category, rel, issuer, description in items:
        ids.append(contract.submit_evidence(agreement_id, category, url_of(rel, base),
                                            item_sha(rel), issuer, description))
    return ids


def deliver(contract, direct_vm, agreement_id: str, items=None, base: str = BASE,
            statement: str = "Delivered as agreed; three runs, all successful.") -> list:
    ids = commit(contract, direct_vm, agreement_id, items or DELIVERY, "seller", base)
    as_sender(direct_vm, "seller")
    contract.submit_delivery(agreement_id, ids, statement)
    return ids


def dispute(contract, direct_vm, agreement_id: str, claim: str = "The delivery is short.",
            evidence_ids=None):
    as_sender(direct_vm, "buyer")
    contract.open_dispute(agreement_id, claim, evidence_ids or [])


def adjudicate(contract, direct_vm, agreement_id: str, panel_answer=None,
               requester: str = "stranger") -> dict:
    stage(direct_vm, panel_answer)
    as_sender(direct_vm, requester)
    adjudication_id = contract.request_adjudication(agreement_id)
    return contract.get_adjudication(adjudication_id)


def finding(record: dict, subject_id: str) -> dict:
    for f in record["criteria"] + record["indicators"]:
        if f["id"] == subject_id:
            return f
    raise KeyError(subject_id)


def present(record: dict) -> list:
    return [f["id"] for f in record["indicators"] if f["state"] == "PRESENT"]


def receipt(record: dict, evidence_id: str) -> dict:
    for r in record["receipts"]:
        if r["evidence_id"] == evidence_id:
            return r
    raise KeyError(evidence_id)


def claimable(contract, name: str) -> int:
    return int(contract.get_claimable(wallet(name))["claimable_atto"])


def assert_conserved(contract, escrow_before: int, *names):
    """Escrow leaves the contract only onto the ledger, and only in full."""
    health = contract.health_check()
    credited = sum(claimable(contract, n) for n in names)
    assert int(health["escrow_held_atto"]) + credited == escrow_before, health
    assert int(health["claimable_atto"]) >= credited


def captured_payload(direct_vm) -> dict:
    result, _leader_fn, _validator_fn = direct_vm._captured_validators[-1]
    return json.loads(result)


def captured_ctx(direct_vm) -> dict:
    _result, leader_fn, _validator_fn = direct_vm._captured_validators[-1]
    for cell in leader_fn.__closure__ or ():
        value = cell.cell_contents
        if isinstance(value, dict) and "subject_id" in value:
            return value
    raise AssertionError("round context not found")


def warp(direct_vm, timestamp: str):
    """Move the transaction clock. genlayer-test 0.29.2's warp() updates the
    VM's datetime but its message refresh copies only sender/origin into the
    SDK's cached gl.message_raw, so a warp after deploy never reaches contract
    code. Set both; this touches the test clock only."""
    direct_vm.warp(timestamp)
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = timestamp


# -- the case catalogue --------------------------------------------------------

CATALOGUE = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
CASES = {c["case_id"]: c for c in CATALOGUE["cases"]}
ONCHAIN_CASES = [c["case_id"] for c in CATALOGUE["cases"] if c["onchain"]]
COMMERCE_CASES = [c["case_id"] for c in CATALOGUE["cases"]
                  if c["onchain"] and c["commerce"]]


def case_items(entry: dict) -> list:
    """A case's evidence in the shape commit()/deliver() take."""
    return [(e["category"], e["path"], e["issuer"], e["description"])
            for e in entry["evidence"]]


def bundle_json(entry: dict, policy_id: str = "SP-000001", base: str = BASE) -> str:
    return json.dumps({
        "agreement_id": "AG-000001",          # the agreement a case simulates
        "buyer": wallet("buyer"), "seller": wallet("seller"),
        "terms": terms_definition(policy_id, base),
        "evidence": [{"category": e["category"], "url": url_of(e["path"], base),
                      "sha256": item_sha(e["path"]), "issuer": e["issuer"],
                      "description": e["description"], "party": e["party"]}
                     for e in entry["evidence"]],
        "seller_statement": entry["seller_statement"],
        "buyer_claim": entry["buyer_claim"]})


def register_case(contract, direct_vm, policy_id: str, case_id: str, version: int = 1,
                  base: str = BASE) -> str:
    entry = CASES[case_id]
    as_sender(direct_vm, "platform")
    return contract.register_adversarial_case(
        policy_id, version, entry["attack_category"], entry["notes"],
        bundle_json(entry, policy_id, base), entry["expected_verdict"],
        entry["expected_seller_bps_min"], entry["expected_seller_bps_max"])


def answer_for(case_id: str):
    return copy.deepcopy(CASES[case_id]["panel_answer"])
