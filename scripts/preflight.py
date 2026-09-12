#!/usr/bin/env python3
"""Preflight: fast structural checks that need no network and no GenVM.

Run before the Direct Mode suite and the linter (CI does). Every check is
named; the script prints PASS/FAIL per check and exits non-zero on any
failure. It proves repository invariants, not contract behaviour - with one
emphasis this repository earns by holding funds: where money can move, and
how many places can move it.

  python scripts/preflight.py
"""

from __future__ import annotations

import hashlib
import io
import json
import pathlib
import re
import subprocess
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "agentguard.py"
FIXTURES = ROOT / "fixtures"
RUNNER = "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6"
FETCH_BYTES_CAP = 8000
VERDICTS = ("FULFILLED", "PARTIALLY_FULFILLED", "NOT_FULFILLED",
            "BUYER_NON_COOPERATION", "SELLER_NON_PERFORMANCE", "MUTUAL_FAULT",
            "EXTERNAL_DEPENDENCY_FAILURE", "INSUFFICIENT_EVIDENCE",
            "CONFLICTING_EVIDENCE", "SOURCE_UNAVAILABLE", "INCONCLUSIVE", "REJECTED")

# Brief section 11: attacks covered only in Direct Mode, and the test that
# covers each. Everything else is a case in fixtures/cases.json.
DIRECT_ONLY = {
    "DIVERGENT_SOURCE_CONTENT": "test_source_divergence_between_nodes",
    "UNSUPPORTED_LEADER_SETTLEMENT": "test_a_leader_inventing_a_satisfied_criterion_is_refused",
    "UNSUPPORTED_VALIDATOR_VERDICT": "test_a_validator_undecided_where_the_leader_decided",
    "PARTIAL_FULFILLMENT_DISAGREEMENT": "test_validators_disagreeing_about_partial_fulfillment",
    "REPLAYED_SUBMISSION": "test_an_agreement_cannot_settle_twice",
    "APPEAL_AFTER_WINDOW": "test_an_appeal_cannot_be_filed_after_its_window",
}

# Brief section 20: every named path and the test that walks it.
BRIEF_TESTS = {
    "fully delivered service": "test_buyer_accepting_pays_the_seller_in_full",
    "partial delivery, partial payment": "test_partial_fulfillment_is_interpolated",
    "buyer accepts": "test_buyer_accepting_pays_the_seller_in_full",
    "dispute resolved": "test_a_dispute_adjudicated_and_settled",
    "appeal with new evidence": "test_an_appeal_reopens_the_same_escrow_under_the_same_terms",
    "missing agreement fields": "test_terms_gate",
    "missing acceptance criteria": "test_terms_gate",
    "unauthorized participant": "test_only_the_buyer_accepts_or_disputes",
    "stale evidence": "test_stale_evidence_cannot_show_current_delivery",
    "source unavailable": "test_an_unreachable_item_holds_the_escrow",
    "duplicate evidence": "test_the_same_bytes_at_two_locations_are_refused_at_the_door",
    "wrong agreement reference": "test_a_log_naming_another_agreement_is_excluded",
    "expired dispute": "test_a_dispute_after_its_window_is_refused",
    "expired appeal": "test_an_appeal_cannot_be_filed_after_its_window",
    "malformed payment amount": "test_price_bounds",
    "allocation greater than escrow": "test_allocations_always_reconcile_to_the_escrow",
    "policy version mismatch": "test_escrow_survives_a_policy_change",
    "replayed submission": "test_an_agreement_cannot_settle_twice",
    "fabricated delivery evidence": "test_case_through_the_commerce_path",
    "buyer falsely rejects": "test_a_false_rejection_does_not_cost_the_seller",
    "seller falsely claims completion": "test_the_sellers_own_word_is_never_a_fact",
    "prompt injection in a document": "test_code_excludes_an_injected_item_without_a_model",
    "prompt injection in a webpage": "test_a_subtle_injection_is_named_by_the_panel",
    "source impersonation": "test_a_source_outside_the_frozen_prefixes_is_not_fetched",
    "conflicting validator outcomes": "test_validators_disagreeing_about_partial_fulfillment",
    "malicious leader settlement": "test_a_payload_carrying_a_settlement_is_refused",
    "external dependency failure": "test_fault_verdicts_take_their_policy_share",
    "buyer non-cooperation": "test_withheld_access_costs_the_buyer_not_the_seller",
    "legitimate variation": "test_a_legitimate_variation_is_not_a_breach",
    "evidence contamination": "test_a_deliverable_sold_twice_is_not_reuse",
    "escrow conservation": "test_the_ledger_is_the_only_way_out",
}

RESULTS = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "  -> " + detail))


def words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.casefold())


def contract_checks():
    raw = CONTRACT.read_bytes()
    text = raw.decode("utf-8")
    lines = text.split("\n")
    check("contract has no CR bytes", b"\r" not in raw)
    check("contract is ASCII", all(b < 128 for b in raw),
          "non-ASCII bytes break the linter and hosted schema encoding")
    check("line 1 is the version comment", lines[0] == "# v0.1.0", lines[0])
    check("line 2 pins the runner", lines[1] == '# { "Depends": "' + RUNNER + '" }',
          lines[1])
    check("line 3 is blank (Depends block is load-bearing)", lines[2] == "")
    for alias in ("py-genlayer:test", "py-genlayer:latest"):
        check("no runner alias " + alias, alias not in text)
    version = re.search(r'^CONTRACT_VERSION = "([^"]+)"', text, re.M)
    check("CONTRACT_VERSION matches the header",
          version is not None and "# v" + version.group(1) == lines[0])
    check("exactly one gl.Contract",
          len(re.findall(r"^class \w+\(gl\.Contract\):", text, re.M)) == 1)
    floats = [t.string for t in tokenize.generate_tokens(io.StringIO(text).readline)
              if (t.type == tokenize.NUMBER and re.search(r"[.eEjJ]", t.string))
              or (t.type == tokenize.NAME and t.string == "float")]
    check("no float literal or float() in the contract (integer arithmetic only)",
          not floats, ", ".join(floats))
    check("no filesystem, clock or randomness in the contract",
          not re.search(r"\bopen\(|\bimport (os|time|random|datetime|requests)\b", text))


def money_checks():
    """Where can value move, and is each place the one the docs name?"""
    text = CONTRACT.read_text(encoding="utf-8")
    transfers = re.findall(r"emit_transfer\(", text)
    check("exactly one transfer call site in the contract", len(transfers) == 1,
          str(len(transfers)) + " found")
    withdraw = re.search(r"def withdraw\(self\).*?(?=\n    @|\n    # --)", text, re.S)
    check("the transfer lives in withdraw()",
          withdraw is not None and "emit_transfer(" in withdraw.group(0))
    check("withdraw clears the ledger before it transfers",
          withdraw is not None
          and withdraw.group(0).index("self.credits[wallet] = u256(0)")
          < withdraw.group(0).index("emit_transfer("))
    payable = re.findall(r"@gl\.public\.write\.payable", text)
    check("exactly one payable method", len(payable) == 1, str(len(payable)) + " found")
    check("only fund_escrow is payable",
          re.search(r"@gl\.public\.write\.payable\s*\n\s*def fund_escrow", text)
          is not None)
    # the eight ways an escrow can leave: the buyer accepting, a finalized
    # adjudication, and the six stalled routes
    settles = re.findall(r"self\._settle\(", text)
    check("every settlement goes through _settle (8 call sites)", len(settles) == 8,
          str(len(settles)) + " found")
    check("_settle refuses allocations that do not reconcile",
          "allocations must reconcile to the escrow exactly" in text)
    check("no contract-to-contract call other than the payout proxy",
          "get_contract_at" not in text)
    check("the escrow total is decremented exactly where it is credited",
          text.count("self.escrow_total_atto = u256(int(self.escrow_total_atto)") == 2)


def secret_checks():
    pattern = re.compile(r"0x[0-9a-fA-F]{64}")
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts \
                or ".data" in path.parts:
            continue
        if path.suffix.lower() not in (".py", ".md", ".json", ".yml", ".yaml", ".txt",
                                       ".toml", ".cfg", ".ini", ".html", ".example", ""):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in content.splitlines():
            if pattern.search(line) and "private" in line.lower():
                offenders.append(str(path.relative_to(ROOT)))
                break
    check("no private keys in the tree", not offenders, ", ".join(offenders))
    env_files = [p.name for p in ROOT.glob(".env*") if p.is_file()
                 and p.name != ".env.example"]
    check("no .env files in the tree (only .env.example)", not env_files,
          ", ".join(env_files))
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    check(".env.example carries no values",
          all(line.strip().endswith("=") for line in example.splitlines()
              if line.strip() and not line.startswith("#")))
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check(".data/ and .env are gitignored", ".data/" in ignore and ".env" in ignore)
    config = (ROOT / "gltest.config.yaml").read_text(encoding="utf-8")
    check("gltest config carries no interpolated secrets", "${" not in config)
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").strip().splitlines()
    check("fixtures are byte-exact in git (-text, last rule)",
          attributes[-1].strip() == "fixtures/** -text")


def fixture_checks():
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_fixtures
    built = generate_fixtures.build()
    differ = [p for p, data in built.items()
              if not (FIXTURES / p).exists() or (FIXTURES / p).read_bytes() != data]
    check("fixtures regenerate byte-exact from scripts/generate_fixtures.py",
          not differ, ", ".join(differ))
    on_disk = {p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob("*")
               if p.is_file()}
    extra = sorted(on_disk - set(built))
    check("no fixture file outside the generator", not extra, ", ".join(extra))

    catalogue = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    cases = catalogue["cases"]
    ids = [c["case_id"] for c in cases]
    check("case ids are unique", len(ids) == len(set(ids)))
    keys = ("case_id", "attack_category", "commerce", "notes", "evidence",
            "seller_statement", "buyer_claim", "expected_verdict",
            "expected_seller_bps_min", "expected_seller_bps_max", "decided_by",
            "panel_answer", "onchain")
    missing = [c["case_id"] for c in cases if any(k not in c for k in keys)]
    check("every case names its input, verdict, share and deciding layer",
          not missing, ", ".join(missing))
    bad = [c["case_id"] for c in cases if c["expected_verdict"] not in VERDICTS
           or not 0 <= c["expected_seller_bps_min"] <= c["expected_seller_bps_max"]
           <= 10000]
    check("every case expects a known verdict and a share within the escrow",
          not bad, ", ".join(bad))
    holding = ("INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "SOURCE_UNAVAILABLE",
               "INCONCLUSIVE")
    paying = [c["case_id"] for c in cases
              if c["expected_verdict"] in holding and c["expected_seller_bps_max"] > 0]
    check("no case expects a holding verdict to pay anyone", not paying,
          ", ".join(paying))

    tests = "\n".join(p.read_text(encoding="utf-8")
                      for p in list((ROOT / "tests" / "direct").glob("*.py"))
                      + [ROOT / "scripts" / "live_scenarios.py"]
                      if p.exists())
    referenced = set()
    for c in cases:
        referenced.update(e["path"] for e in c["evidence"])
    unused = sorted(p for p in on_disk
                    if p not in referenced and p not in ("cases.json", "wallets.json")
                    and p not in tests)
    check("every evidence document is used by a case or a test", not unused,
          ", ".join(unused))

    docs = [p for p in FIXTURES.rglob("*") if p.is_file()
            and p.name not in ("cases.json", "wallets.json")]
    big = [p.name for p in docs if p.stat().st_size > FETCH_BYTES_CAP]
    check("every evidence document fits the fetch cap", not big, ", ".join(big))
    cr = [p.name for p in docs if b"\r" in p.read_bytes()]
    check("evidence documents are LF-only (hashes survive checkouts)", not cr,
          ", ".join(cr))

    ungrounded = []
    for c in cases:
        answer = c["panel_answer"] or {}
        files = {"E" + str(i + 1): e["path"] for i, e in enumerate(c["evidence"])}
        entries = list((answer.get("criteria") or {}).values()) + \
            list((answer.get("indicators") or {}).values())
        for entry in entries:
            for q in entry.get("quotes", []):
                source = words((FIXTURES / files[q["evidence_id"]]).read_text(
                    encoding="utf-8"))
                needle = words(q["text"])
                if not any(source[i:i + len(needle)] == needle
                           for i in range(len(source))):
                    ungrounded.append(c["case_id"] + " " + q["evidence_id"])
    check("every recorded panel quote is verbatim in its document",
          not ungrounded, "; ".join(ungrounded))

    favours = {"BUYER_WITHHELD_INPUT": "seller", "EXTERNAL_DEPENDENCY_FAILED": "seller",
               "SELLER_SCOPE_CHANGE": "buyer", "BUYER_CRITERIA_CHANGE": "seller"}
    self_serving = []
    for c in cases:
        answer = c["panel_answer"] or {}
        parties = {"E" + str(i + 1): e["party"] for i, e in enumerate(c["evidence"])}
        for name, entry in (answer.get("indicators") or {}).items():
            if entry.get("state") != "PRESENT" or name not in favours:
                continue
            if all(parties.get(q["evidence_id"]) == favours[name]
                   for q in entry.get("quotes", [])):
                self_serving.append(c["case_id"] + " " + name)
    check("no recorded finding rests only on the words of the agent it favours",
          not self_serving, "; ".join(self_serving))


def coverage_checks():
    tests = "\n".join(p.read_text(encoding="utf-8")
                      for p in (ROOT / "tests" / "direct").glob("test_*.py"))
    catalogue = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    onchain = {c["attack_category"] for c in catalogue["cases"] if c["onchain"]}
    contract = CONTRACT.read_text(encoding="utf-8")
    listed = re.search(r"ATTACK_CATEGORIES = \((.*?)\)\n", contract, re.S).group(1)
    brief = [a for a in re.findall(r'"([A-Z_]+)"', listed)
             if a not in ("LEGITIMATE_BASELINE", "OTHER")]
    check("the contract lists the brief's 30 attack categories", len(brief) == 30,
          str(len(brief)))
    uncovered = [a for a in brief if a not in onchain
                 and "def " + DIRECT_ONLY.get(a, "-") + "(" not in tests]
    check("every attack category is a case or a named Direct Mode test",
          not uncovered, ", ".join(uncovered))
    missing = [path for path, fn in BRIEF_TESTS.items() if "def " + fn + "(" not in tests]
    check("every brief section 20 path has a named test", not missing,
          ", ".join(missing))
    names = ("test_contract_smoke.py", "test_agreement_validation.py",
             "test_settlement_bounds.py", "test_evidence_validation.py",
             "test_prompt_injection.py", "test_adversarial_cases.py",
             "test_consensus_equivalence.py", "test_appeals.py")
    absent = [n for n in names if not (ROOT / "tests" / "direct" / n).exists()]
    check("the brief's eight test modules exist", not absent, ", ".join(absent))


DOCS = ("README.md", "DECISION.md", "SUBMISSION.md", "docs/architecture.md",
        "docs/agreement-policy.md", "docs/evidence-policy.md", "docs/settlement.md",
        "docs/threat-model.md", "docs/consensus.md", "docs/integration.md",
        "docs/deployment.md")


def docs_checks():
    missing = [name for name in DOCS if not (ROOT / name).exists()]
    check("every document the brief names exists", not missing, ", ".join(missing))

    # every private symbol a document anchors to must still be in the contract
    source = CONTRACT.read_text(encoding="utf-8")
    stray = []
    for name in DOCS:
        path = ROOT / name
        if not path.exists():
            continue
        for token in set(re.findall(r"`(_[a-z][a-z0-9_]*)`",
                                    path.read_text(encoding="utf-8"))):
            if token not in source:
                stray.append(name + ":" + token)
    check("docs anchor only to symbols the contract still has", not stray,
          ", ".join(sorted(stray)))

    # the README's Direct Mode count is the suite's own count, not a memory
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    claimed = re.search(r"`python -m pytest tests/direct -q` \| (\d+) passed", readme)
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/direct", "--collect-only", "-q",
         "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True)
    found = re.search(r"(\d+) tests? collected", collected.stdout)
    check("the README's Direct Mode count is the suite's own count",
          bool(claimed and found and claimed.group(1) == found.group(1)),
          (claimed.group(1) if claimed else "unstated") + " claimed vs "
          + (found.group(1) if found else "uncollected"))


def address_checks():
    record = ROOT / "deploy" / "deployment.json"
    if not record.exists():
        check("deployment record (skipped: not deployed yet)", True)
        return
    deployment = json.loads(record.read_text(encoding="utf-8"))
    allowed = {deployment["contract_address"].lower()}
    allowed |= {a.lower() for a in deployment.get("other_addresses", {}).values()}
    wallets = json.loads((FIXTURES / "wallets.json").read_text(encoding="utf-8"))
    allowed |= {a.lower() for a in wallets.values()}
    stray = []
    docs = [ROOT / "README.md", ROOT / "SUBMISSION.md", ROOT / "DECISION.md"] + \
        list((ROOT / "docs").glob("*.md"))
    for path in docs:
        if not path.exists():
            continue
        for address in re.findall(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])",
                                  path.read_text(encoding="utf-8")):
            if address.lower() not in allowed:
                stray.append(path.name + ":" + address)
    placeholders = [p.name for p in docs if p.exists()
                    and re.search(r"LIVE_SUMMARY|TO_BE_FILLED|TODO",
                                  p.read_text(encoding="utf-8"))]
    check("no unfilled placeholders in the docs", not placeholders, ", ".join(placeholders))
    check("docs name only the recorded addresses (one canonical deployment)",
          not stray, ", ".join(sorted(set(stray))))
    source = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    check("deployment record names the current contract bytes",
          deployment.get("source_sha256") == source,
          "record " + str(deployment.get("source_sha256")) + " vs tree " + source)


def main():
    contract_checks()
    money_checks()
    secret_checks()
    fixture_checks()
    coverage_checks()
    docs_checks()
    address_checks()
    failed = [r for r in RESULTS if not r[1]]
    print("\n" + str(len(RESULTS)) + " checks, " + str(len(failed)) + " failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
