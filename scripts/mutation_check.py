#!/usr/bin/env python3
"""Mutation kill check: prove the Direct Mode suite pins each load-bearing
guard, not merely that the code passes today.

For each mutation the contract is copied to a scratch directory with ONE
guard mechanically broken, and the whole Direct Mode suite runs against the
copy. A mutation is KILLED when the suite fails and SURVIVED when it passes
(an unpinned guard). The run starts with an accept-control: the unmodified
copy must pass, or every kill would be vacuous.

Anchors are code TEXT, never line numbers. An anchor that is not found
exactly once is reported as ANCHOR MISSING - the guard moved or was deleted,
which is its own finding. Equivalent mutants (a guard a second guard makes
unobservable) are not listed; the ones considered and excluded are named at
the bottom of this file with the reason.

Run:  python scripts/mutation_check.py             (full sweep)
      python scripts/mutation_check.py --anchors   (anchor check only)
      python scripts/mutation_check.py --only gate (only mutations whose name
                                                    contains "gate")
      python scripts/mutation_check.py --jobs 3    (three scratch copies at
                                                    once; default 1)

Each job gets its own copy of the repository, so mutations never share a
contract file. Results are printed in list order once the sweep finishes,
with a progress line per mutation as it completes.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = "contracts/agentguard.py"

MUTATIONS = [
    # -- verdict precedence (_derive) ------------------------------------------------
    ("unreachable or changed source no longer SOURCE_UNAVAILABLE",
     "    if ROW_UNAVAILABLE in statuses or ROW_HASH_MISMATCH in statuses:\n",
     "    if False:\n"),
    ("changed bytes no longer SOURCE_UNAVAILABLE",
     "    if ROW_UNAVAILABLE in statuses or ROW_HASH_MISMATCH in statuses:\n",
     "    if ROW_UNAVAILABLE in statuses:\n"),
    ("oversized or malformed item no longer INCONCLUSIVE",
     "    elif ROW_TOO_LARGE in statuses or ROW_UNPARSEABLE in statuses:\n",
     "    elif False:\n"),
    ("no usable evidence still settles",
     "    elif len(eligible) == 0 or len(eligible) < policy[\"minimum_evidence_items\"]:\n",
     "    elif False:\n"),
    ("policy minimum evidence count ignored",
     "    elif len(eligible) == 0 or len(eligible) < policy[\"minimum_evidence_items\"]:\n",
     "    elif len(eligible) == 0:\n"),
    ("fabrication or injection no longer CONFLICTING_EVIDENCE",
     "    elif \"EVIDENCE_MANIPULATION\" in present or \"INSTRUCTION_INJECTION\" in present:\n",
     "    elif False:\n"),
    ("a panel-found injection still settles",
     "    elif \"EVIDENCE_MANIPULATION\" in present or \"INSTRUCTION_INJECTION\" in present:\n",
     "    elif \"EVIDENCE_MANIPULATION\" in present:\n"),
    ("an undecided question no longer INCONCLUSIVE",
     "    elif undecided:\n",
     "    elif False:\n"),
    ("both agents at fault collapses to one",
     "    elif \"BUYER_WITHHELD_INPUT\" in present and \"SELLER_SCOPE_CHANGE\" in present:\n",
     "    elif False:\n"),
    ("a withholding buyer is not recognized",
     "    elif \"BUYER_WITHHELD_INPUT\" in present:\n",
     "    elif False:\n"),
    ("a failed dependency is not recognized",
     "    elif \"EXTERNAL_DEPENDENCY_FAILED\" in present:\n",
     "    elif False:\n"),
    ("a substituted service is not NOT_FULFILLED",
     "    elif \"SELLER_SCOPE_CHANGE\" in present:\n",
     "    elif False:\n"),
    ("unverifiable weight limit ignored",
     "    elif unverifiable_share > policy[\"unverifiable_weight_limit\"]:\n",
     "    elif False:\n"),
    ("full threshold off by one",
     "    elif level >= policy[\"full_threshold\"]:\n",
     "    elif level > policy[\"full_threshold\"]:\n"),
    ("partial threshold off by one",
     "    elif level >= policy[\"partial_threshold\"]:\n",
     "    elif level > policy[\"partial_threshold\"]:\n"),
    ("a holding verdict settles",
     "    settleable = verdict in SETTLING\n",
     "    settleable = True\n"),
    ("a buyer who moved the criteria bears no fault",
     "    elif verdict == \"MUTUAL_FAULT\" or \"BUYER_CRITERIA_CHANGE\" in present:\n",
     "    elif verdict == \"MUTUAL_FAULT\":\n"),
    ("unverifiable weight does not lower confidence",
     "    elif any(f[\"state\"] == UNVERIFIABLE for f in criteria):\n",
     "    elif False:\n"),
    # -- the fulfillment level (_levels) ---------------------------------------------
    ("optional criteria are scored",
     "        if kind == \"OPTIONAL\":\n            continue\n",
     "        if False:\n            continue\n"),
    ("unverifiable weight counted as satisfied",
     "        elif f[\"state\"] == UNVERIFIABLE:\n            unverifiable = unverifiable + weight\n",
     "        elif f[\"state\"] == UNVERIFIABLE:\n            satisfied = satisfied + weight\n"),
    ("the level rounds up",
     "    level = satisfied * 100 // total if total > 0 else 0\n",
     "    level = (satisfied * 100 + total - 1) // total if total > 0 else 0\n"),
    # -- the split (_seller_bps, _split) ---------------------------------------------
    ("a fulfilled delivery is paid less than the escrow",
     "    if verdict == \"FULFILLED\":\n        return BPS\n",
     "    if verdict == \"FULFILLED\":\n        return BPS - 1\n"),
    ("the partial share is not clamped to the whole escrow",
     "        return min(BPS, floor + (BPS - floor) * (level - low) // (high - low))\n",
     "        return floor + (BPS - floor) * (level - low) // (high - low)\n"),
    ("the policy's floor at the partial threshold is ignored",
     "        floor = policy[\"partial_seller_bps_at_threshold\"]\n",
     "        floor = 0\n"),
    ("the not-fulfilled share is ignored",
     "    if verdict == \"NOT_FULFILLED\":\n        return policy[\"not_fulfilled_seller_bps\"]\n",
     "    if verdict == \"NOT_FULFILLED\":\n        return 0\n"),
    ("the buyer-non-cooperation share is ignored",
     "    if verdict == \"BUYER_NON_COOPERATION\":\n"
     "        return policy[\"buyer_non_cooperation_seller_bps\"]\n",
     "    if verdict == \"BUYER_NON_COOPERATION\":\n        return BPS\n"),
    ("the external-failure share is ignored",
     "    if verdict == \"EXTERNAL_DEPENDENCY_FAILURE\":\n"
     "        return policy[\"external_failure_seller_bps\"]\n",
     "    if verdict == \"EXTERNAL_DEPENDENCY_FAILURE\":\n        return 0\n"),
    ("a non-performing seller is paid",
     "    return 0            # SELLER_NON_PERFORMANCE, REJECTED and every hold\n",
     "    return BPS          # SELLER_NON_PERFORMANCE, REJECTED and every hold\n"),
    ("the remainder of the division goes to the seller",
     "    seller = escrow * bps // BPS\n",
     "    seller = (escrow * bps + BPS - 1) // BPS\n"),
    # -- the escrow (_settle, fund_escrow, withdraw) ----------------------------------
    ("allocations need not reconcile to the escrow",
     "        if seller_atto + buyer_atto != escrow:\n",
     "        if False:\n"),
    ("a negative allocation is allowed",
     "        if seller_atto < 0 or buyer_atto < 0:\n",
     "        if False:\n"),
    ("escrow accounting is not checked",
     "        if escrow > int(self.escrow_total_atto):\n",
     "        if False:\n"),
    ("settlement does not close the agreement",
     "        agreement.settlement_route = route\n        agreement.status = \"FINALIZED\"\n",
     "        agreement.settlement_route = route\n"),
    ("the escrow need not equal the agreed price",
     "        if value != int(agreement.price_atto):\n",
     "        if False:\n"),
    ("the ledger is not cleared before the transfer",
     "        self.credits[wallet] = u256(0)\n"
     "        self.credits_total_atto = u256(int(self.credits_total_atto) - amount)\n",
     "        pass\n"),
    ("an empty balance may be withdrawn",
     "        if amount <= 0:\n            self._fail(\"nothing to withdraw\")\n",
     "        if False:\n            self._fail(\"nothing to withdraw\")\n"),
    # -- lifecycle, windows and access control ----------------------------------------
    ("any sender may act as the buyer",
     "        if role == \"buyer\" and sender != agreement.buyer:\n",
     "        if False:\n"),
    ("any sender may act as the seller",
     "        if role == \"seller\" and sender != agreement.seller:\n",
     "        if False:\n"),
    ("a stranger may act as a party",
     "        if role == \"either\" and sender != agreement.buyer and sender != agreement.seller:\n",
     "        if False:\n"),
    ("the agreement state is not required",
     "        if str(agreement.status) not in states:\n",
     "        if False:\n"),
    ("an agreement may be accepted after its deadline",
     "        if _iso_epoch(terms[\"deadline\"]) <= _iso_epoch(now):\n"
     "            self._fail(\"the deadline is already past; propose a new agreement\")\n",
     "        if False:\n"
     "            self._fail(\"the deadline is already past; propose a new agreement\")\n"),
    ("the dispute window is not enforced",
     "        if _iso_epoch(now) > deadline:\n            self._fail(\"the dispute window has closed\")\n",
     "        if False:\n            self._fail(\"the dispute window has closed\")\n"),
    ("the same bytes may be committed twice to one agreement",
     "            if str(ev.sha256) == sha256:\n",
     "            if False:\n"),
    ("the same location may be committed twice",
     "            if str(ev.url) == canonical:\n",
     "            if False:\n"),
    ("the evidence cap is off by one",
     "        if len(agreement.evidence_ids) >= MAX_EVIDENCE:\n",
     "        if len(agreement.evidence_ids) > MAX_EVIDENCE:\n"),
    ("the seller may deliver the buyer's evidence",
     "            if str(ev.party) != \"seller\":\n"
     "                self._fail(\"the seller delivers the seller's own evidence\")\n",
     "            if False:\n"
     "                self._fail(\"the seller delivers the seller's own evidence\")\n"),
    ("a party may point at the other's evidence",
     "            if str(ev.party) != party:\n"
     "                self._fail(\"a party may only point at its own evidence\")\n",
     "            if False:\n"
     "                self._fail(\"a party may only point at its own evidence\")\n"),
    ("the seller may answer a dispute twice",
     "        if str(agreement.seller_counterclaim) != \"\":\n",
     "        if False:\n"),
    # -- appeals ----------------------------------------------------------------------
    ("the appeal window is not enforced",
     "        if _iso_epoch(now) > _iso_epoch(str(agreement.appeal_deadline)):\n"
     "            self._fail(\"the appeal window has closed\")\n",
     "        if False:\n            self._fail(\"the appeal window has closed\")\n"),
    ("appeals are not capped by the policy",
     "        if len(agreement.appeal_ids) >= policy[\"maximum_appeals\"]:\n",
     "        if False:\n"),
    ("an appeal may re-submit evidence the adjudication read",
     "            if eid in judged or eid in seen:\n",
     "            if eid in seen:\n"),
    ("an appellant may add the other agent's evidence",
     "            if str(ev.party) != party:\n"
     "                self._fail(\"an appellant may only add its own evidence\")\n",
     "            if False:\n"
     "                self._fail(\"an appellant may only add its own evidence\")\n"),
    ("an appeal may be heard twice",
     "        if str(appeal.status) != APPEAL_OPEN:\n"
     "            self._fail(\"this appeal has already been heard\")\n",
     "        if False:\n            self._fail(\"this appeal has already been heard\")\n"),
    ("a readjudication may run on a settled agreement",
     "        agreement = self._agreement(str(appeal.agreement_id))\n"
     "        self._require_state(agreement, (\"ADJUDICATED\",))\n",
     "        agreement = self._agreement(str(appeal.agreement_id))\n"),
    # -- finalization and the stalled routes ------------------------------------------
    ("settlement inside the appeal window",
     "        if _iso_epoch(now) <= _iso_epoch(str(agreement.appeal_deadline)):\n"
     "            self._fail(\"the appeal window is still open\")\n",
     "        if False:\n            self._fail(\"the appeal window is still open\")\n"),
    ("settlement with an appeal waiting to be heard",
     "        for aid in agreement.appeal_ids:\n"
     "            if str(self.appeals.get(str(aid)).status) == APPEAL_OPEN:\n"
     "                self._fail(\"an appeal is waiting to be heard\")\n"
     "        record = self._standing(agreement)\n",
     "        record = self._standing(agreement)\n"),
    ("a holding verdict is finalized",
     "        if not record[\"settleable\"]:\n"
     "            self._fail(\"this adjudication does not settle (\" + record[\"verdict\"]\n",
     "        if False:\n"
     "            self._fail(\"this adjudication does not settle (\" + record[\"verdict\"]\n"),
    ("a stalled claim before the seller's time is up",
     "            if at <= due:\n                self._fail(\"the seller still has time to deliver\")\n",
     "            if False:\n                self._fail(\"the seller still has time to deliver\")\n"),
    ("a stalled claim before the buyer's time is up",
     "            if at <= due:\n"
     "                self._fail(\"the buyer still has time to accept or dispute\")\n",
     "            if False:\n"
     "                self._fail(\"the buyer still has time to accept or dispute\")\n"),
    ("a stalled claim while an adjudication can still be asked for",
     "            if at <= _iso_epoch(str(agreement.disputed_at)) + stall:\n",
     "            if False:\n"),
    ("a stalled claim before the appeal window has passed",
     "            if at <= _iso_epoch(str(agreement.appeal_deadline)) + stall:\n",
     "            if False:\n"),
    ("the policy's silence rule is ignored",
     "            if policy[\"silence_is_acceptance\"]:\n",
     "            if False:\n"),
    ("silence always pays the seller",
     "            if policy[\"silence_is_acceptance\"]:\n",
     "            if True:\n"),
    ("an unsettled adjudication pays the seller",
     "            self._settle(agreement, 0, escrow, \"UNSETTLED_ADJUDICATION\", now)\n",
     "            self._settle(agreement, escrow, 0, \"UNSETTLED_ADJUDICATION\", now)\n"),
    ("a stalled claim ignores a pending appeal",
     "            if record[\"settleable\"]:\n"
     "                for aid in agreement.appeal_ids:\n"
     "                    if str(self.appeals.get(str(aid)).status) == APPEAL_OPEN:\n"
     "                        self._fail(\"an appeal is waiting to be heard\")\n",
     "            if record[\"settleable\"]:\n                for aid in []:\n                    pass\n"),
    ("a live agreement is claimable as stalled",
     "        self._fail(\"this agreement is not stalled\")\n",
     "        self._settle(agreement, 0, escrow, \"NO_DELIVERY\", now)\n"),
    # -- provenance and admission ------------------------------------------------------
    ("a category the agreement does not source is allowed",
     "    rule = _source_rule(terms, category)\n    if rule is None:\n        return (False, False, \"\")\n",
     "    rule = _source_rule(terms, category)\n    if rule is None:\n        return (True, True, \"\")\n"),
    ("any location is trusted",
     "        if canonical_url.startswith(canonical_prefix):\n",
     "        if True:\n"),
    ("an agent's own message is treated as a trusted source",
     "    if category == SELF_ATTESTED:\n        return (True, False, \"\")\n",
     "    if category == SELF_ATTESTED:\n        return (True, True, \"\")\n"),
    ("an agent's own message is refused",
     "    if category == SELF_ATTESTED:\n        return (True, False, \"\")\n",
     "    if category == SELF_ATTESTED:\n        return (False, False, \"\")\n"),
    ("http locations accepted",
     "    if not url.startswith(\"https://\"):\n",
     "    if False:\n"),
    ("credentials in a url accepted",
     "    if \"@\" in authority:\n",
     "    if False:\n"),
    ("a port other than 443 accepted",
     "        if port != \"443\":\n",
     "        if False:\n"),
    ("an IP literal host accepted",
     "    if all_numeric or labels[-1].isdigit():\n",
     "    if False:\n"),
    ("localhost accepted",
     "    if host == \"localhost\" or host.endswith(\".localhost\"):\n",
     "    if False:\n"),
    ("an internal name accepted",
     "    if host.endswith(\".local\") or host.endswith(\".internal\") \\\n"
     "            or host.endswith(\".home.arpa\") or host.endswith(\".lan\"):\n",
     "    if False:\n"),
    ("dot-segments accepted",
     "        if seg in (\".\", \"..\"):\n",
     "        if False:\n"),
    ("encoded separators accepted",
     "    if \"%2e\" in lowered or \"%2f\" in lowered or \"%5c\" in lowered:\n",
     "    if False:\n"),
    ("a url fragment accepted",
     "    if \"#\" in rest:\n",
     "    if False:\n"),
    ("booleans accepted as integers",
     "    return isinstance(value, int) and not isinstance(value, bool)\n",
     "    return isinstance(value, int)\n"),
    # -- retrieval and byte verification -----------------------------------------------
    ("bytes read without the hash check",
     "    if hashlib.sha256(body).hexdigest() != item[\"sha256\"]:\n",
     "    if False:\n"),
    ("an item outside the allowlist is fetched",
     "    if not item[\"allowed\"]:\n        row[\"status\"] = ROW_NOT_ALLOWED\n",
     "    if False:\n        row[\"status\"] = ROW_NOT_ALLOWED\n"),
    ("oversized bytes are read",
     "    if len(body) > FETCH_BYTES_CAP:\n",
     "    if False:\n"),
    ("error responses are read",
     "    if status < 200 or status >= 300 or body is None or len(body) == 0:\n",
     "    if body is None or len(body) == 0:\n"),
    ("empty bytes are examined",
     "    if text.strip() == \"\":\n",
     "    if False:\n"),
    ("a structured item that breaks its schema is still examined",
     "            if _structured_facts(text, item[\"category\"], item[\"evidence_id\"]) is None:\n",
     "            if False:\n"),
    ("a float or a boolean passes as a structured fact",
     "def _amount(value) -> bool:\n    return _int_in(value, 0, 10 ** 15)\n",
     "def _amount(value) -> bool:\n    return isinstance(value, (int, float))\n"),
    ("a test report whose parts do not sum is a fact",
     "        if doc[\"passed\"] + doc[\"failed\"] != doc[\"total\"]:\n",
     "        if False:\n"),
    ("a run finishing before it started is a fact",
     "            if _iso_epoch(run[\"finished\"]) < _iso_epoch(run[\"started\"]):\n",
     "            if False:\n"),
    ("a document declaring another type is read as its category",
     "    if doc[\"document_type\"] != category:\n",
     "    if False:\n"),
    # -- code scans and code indicators -------------------------------------------------
    ("injection markers are not scanned",
     "        if _injection_hits(texts[eid]):\n            markers.append(eid)\n",
     "        if False:\n            markers.append(eid)\n"),
    ("hidden text is not scanned",
     "        if _hidden_hits(texts[eid]):\n            hidden.append(eid)\n",
     "        if False:\n            hidden.append(eid)\n"),
    ("hidden characters are not checked",
     "    if any(ch in body for ch in HIDDEN_CHARACTERS):\n        return True\n",
     "    if False:\n        return True\n"),
    ("hidden styling is not checked",
     "    return any(style in folded for style in HIDDEN_STYLES)\n",
     "    return False\n"),
    ("a byte-order mark counts as hidden text",
     "    body = text[1:] if text.startswith(\"\\ufeff\") else text\n",
     "    body = text\n"),
    ("another agreement's paperwork is not noticed",
     "        elif item[\"category\"] not in STRUCTURED \\\n"
     "                and _names_another_agreement(texts[eid], ctx[\"agreement_id\"]):\n",
     "        elif False:\n"),
    ("a six-digit agreement id is not required",
     "        if len(digits) == 6 and digits.isdigit() and candidate != mine:\n",
     "        if candidate != mine:\n"),
    ("duplicate evidence is not flagged",
     "        if digest in seen:\n",
     "        if False:\n"),
    ("facts about another agreement are not flagged",
     "    unlinked = [f[\"evidence_id\"] for f in facts\n"
     "                if f[\"agreement_id\"] != ctx[\"agreement_id\"]]\n",
     "    unlinked = []\n"),
    ("stale evidence is not flagged",
     "    stale = [f[\"evidence_id\"] for f in facts\n"
     "             if _iso_epoch(ctx[\"now\"]) - _iso_epoch(f[\"as_of\"]) > limit]\n",
     "    stale = []\n"),
    ("a missed deadline is not flagged",
     "    if ctx[\"delivered_at\"] != \"\" and _iso_epoch(ctx[\"delivered_at\"]) > \\\n",
     "    if False and _iso_epoch(ctx[\"delivered_at\"]) > \\\n"),
    ("the cure period is not allowed for",
     "            _iso_epoch(ctx[\"terms\"][\"deadline\"]) + ctx[\"terms\"][\"cure_period_seconds\"]:\n",
     "            _iso_epoch(ctx[\"terms\"][\"deadline\"]):\n"),
    ("absence is declared without examining every item",
     "    if not all(e in examined for e in considered):\n"
     "        return _finding(name, UNDETERMINED, BY_CODE)\n",
     "    if False:\n        return _finding(name, UNDETERMINED, BY_CODE)\n"),
    ("a tainted item may still satisfy a criterion",
     "        if f[\"id\"] in TAINTING and f[\"state\"] == PRESENT:\n",
     "        if False:\n"),
    # -- the registry -------------------------------------------------------------------
    ("the first committer is flagged for its own bytes",
     "            if seq is None or int(first_seq) < seq:\n",
     "            if True:\n"),
    ("an agreement's own earlier commitment is flagged",
     "            if first_agreement == ctx[\"agreement_id\"]:\n                continue\n",
     "            if False:\n                continue\n"),
    ("a registry entry is overwritten by later committers",
     "        if self.evidence_registry.get(digest) is None:\n",
     "        if True:\n"),
    ("a legitimately resold artifact is flagged as reuse",
     "            if it[\"category\"] == \"DELIVERABLE\":\n",
     "            if False:\n"),
    # -- the round plan ------------------------------------------------------------------
    ("a criterion with no readable evidence is left to the panel",
     "        elif len(pool) == 0:\n",
     "        elif False:\n"),
    ("the evidence pool ignores the criterion's categories",
     "        pool = [e for e in eligible if kinds[e] in c[\"evidence_categories\"]]\n",
     "        pool = list(eligible)\n"),
    ("the panel is convened on unexamined evidence",
     "    if any(row_of[e][\"status\"] != ROW_EXAMINED for e in allowed):\n"
     "        skip = SKIP_NOT_EXAMINED\n",
     "    if False:\n        skip = SKIP_NOT_EXAMINED\n"),
    ("the panel is convened with no eligible evidence",
     "    elif len(eligible) == 0:\n        skip = SKIP_NO_EVIDENCE\n",
     "    elif False:\n        skip = SKIP_NO_EVIDENCE\n"),
    # -- the panel's answer ---------------------------------------------------------------
    ("a decided criterion is accepted without a quote",
     "        if state is None or (decided and len(quotes) == 0):\n",
     "        if state is None:\n"),
    ("an indicator is accepted without meeting its quote rule",
     "        if state is None or (state == PRESENT and not satisfied):\n",
     "        if state is None:\n"),
    ("a finding may rest only on the agent it favours",
     "    return any(parties.get(e) != benefits for e in distinct)\n",
     "    return True\n"),
    ("support is accepted without any quoted item",
     "    if len(distinct) < min_items:\n        return False\n",
     "    if False:\n        return False\n"),
    ("a quote from an ineligible item grounds",
     "    if quote[\"evidence_id\"] not in eligible:\n        return False\n",
     "    if False:\n        return False\n"),
    ("quote grounding is skipped",
     "        position = _find_run(haystack, words, position)\n        if position < 0:\n",
     "        position = 0\n        if position < 0:\n"),
    ("elided fragments may appear out of order",
     "        position = _find_run(haystack, words, position)\n",
     "        position = _find_run(haystack, words, 0)\n"),
    ("a one-word fragment grounds",
     "        if len(words) == 1:\n            return False\n",
     "        if False:\n            return False\n"),
    ("a quote below the minimum length is kept",
     "    if len(text) < QUOTE_MIN:\n        return None\n",
     "    if False:\n        return None\n"),
    ("evidence ids outside the eligible pool are kept",
     "    return (state, [e for e in eligible if e in ids], quotes,\n",
     "    return (state, ids, quotes,\n"),
    ("a state outside the vocabulary is accepted",
     "    if state not in vocab:\n        state = None\n",
     "    if False:\n        state = None\n"),
    ("an answer with no sections is read as an answer",
     "    if not isinstance(raw, dict):\n        return None\n",
     "    if not isinstance(raw, dict):\n        return {\"criteria\": {}, \"indicators\": {}}\n"),
    ("note trimming is not idempotent",
     "    return \" \".join(\"\".join(chars).split())[:NOTE_CAP].strip()\n",
     "    return \" \".join(\"\".join(chars).split())[:NOTE_CAP]\n"),
    # -- the structural gate (_parse_payload) ----------------------------------------------
    ("the gate accepts extra or missing payload keys",
     "    if not isinstance(p, dict) or sorted(p.keys()) != sorted(PAYLOAD_KEYS):\n",
     "    if not isinstance(p, dict):\n"),
    ("the gate accepts a payload bound to other terms",
     "    if p[\"terms_hash\"] != ctx[\"terms_hash\"] \\\n"
     "            or p[\"evidence_commitment\"] != ctx[\"evidence_commitment\"]:\n        return None\n",
     "    if False:\n        return None\n"),
    ("the gate accepts a payload from another round",
     "    if p[\"subject_id\"] != ctx[\"subject_id\"] or not _is_int(p[\"round\"]) \\\n"
     "            or p[\"round\"] != ctx[\"round\"] or p[\"now\"] != ctx[\"now\"]:\n        return None\n",
     "    if False:\n        return None\n"),
    ("the gate does not recheck rows against the allowlist",
     "        if (r[\"status\"] == ROW_NOT_ALLOWED) != (not items[i][\"allowed\"]):\n",
     "        if False:\n"),
    ("the gate accepts a byte count for unverified bytes",
     "        elif r[\"byte_count\"] != 0:\n            return None\n",
     "        elif False:\n            return None\n"),
    ("the gate accepts facts the node did not read",
     "    if not isinstance(facts, list) or \\\n"
     "            [f.get(\"evidence_id\") if isinstance(f, dict) else None\n"
     "             for f in facts] != expected_facts:\n        return None\n",
     "    if not isinstance(facts, list):\n        return None\n"),
    ("the gate does not revalidate each fact",
     "        if not _valid_fact(f, by_id[f[\"evidence_id\"]]):\n            return None\n",
     "        if False:\n            return None\n"),
    ("the gate does not recompute the scans",
     "    for key in (\"linked\", \"foreign\", \"markers\", \"hidden\"):\n",
     "    for key in ():\n"),
    ("the gate does not recompute the panel decision",
     "    if p[\"panel_reason\"] != plan[\"skip\"]:\n        return None\n",
     "    if False:\n        return None\n"),
    ("the gate accepts an assessed panel where code skipped it",
     "    if plan[\"skip\"] != \"\":\n        if p[\"panel_state\"] != PANEL_SKIPPED:\n            return None\n",
     "    if plan[\"skip\"] != \"\":\n        if False:\n            return None\n"),
    ("the gate does not recompute the code indicators",
     "    for i in range(len(CODE_INDICATORS)):\n"
     "        if indicators[i] != plan[\"code_indicators\"][i]:\n            return None\n",
     "    for i in range(0):\n"
     "        if indicators[i] != plan[\"code_indicators\"][i]:\n            return None\n"),
    ("the gate does not re-ground quotes",
     "        if not _quote_grounded(q, eligible, texts):\n            return False\n",
     "        if False:\n            return False\n"),
    ("the gate accepts a decided criterion with no quote",
     "        if f[\"state\"] in (SATISFIED, NOT_SATISFIED) and len(f[\"quotes\"]) == 0:\n"
     "            return None\n",
     "        if False:\n            return None\n"),
    ("the gate accepts an indicator whose support rule fails",
     "        if f[\"state\"] == PRESENT and not _support_satisfies(min_items, benefits,\n"
     "                                                            f[\"quotes\"], parties):\n"
     "            return None\n",
     "        if False:\n            return None\n"),
    ("the gate accepts findings outside the eligible pool",
     "    if [e for e in eligible if e in f[\"evidence_ids\"]] != f[\"evidence_ids\"]:\n"
     "        return False\n",
     "    if False:\n        return False\n"),
    ("the gate accepts a finding attributed to code",
     "    if f[\"by\"] != BY_PANEL or f[\"state\"] not in vocab:\n        return False\n",
     "    if False:\n        return False\n"),
    ("the gate accepts fixed findings the panel rewrote",
     "        if fixed is not None:\n            if f != fixed:\n                return None\n            continue\n"
     "        if not _check_panel_finding(f, c[\"criterion_id\"], eligible,\n",
     "        if fixed is not None:\n            continue\n"
     "        if not _check_panel_finding(f, c[\"criterion_id\"], eligible,\n"),
    ("the gate accepts skipped findings that differ",
     "        if criteria != expect[0] or indicators != plan[\"code_indicators\"] + expect[1]:\n"
     "            return None\n",
     "        if False:\n            return None\n"),
    ("the gate accepts a quote longer than the cap",
     "        if len(q[\"text\"]) < QUOTE_MIN or len(q[\"text\"]) > QUOTE_CAP \\\n"
     "                or q[\"text\"] != q[\"text\"].strip():\n            return False\n",
     "        if False:\n            return False\n"),
    ("the gate accepts more quotes than the cap",
     "    if len(f[\"quotes\"]) > MAX_QUOTES or \\\n",
     "    if False or \\\n"),
    ("the gate accepts a finding whose keys differ",
     "    if not isinstance(f, dict) or sorted(f.keys()) != sorted(FINDING_KEYS):\n",
     "    if not isinstance(f, dict):\n"),
    # -- consensus: the validator's own comparison ------------------------------------------
    ("a validator accepts a payload that fails the gate",
     "        if parsed is None:\n"
     "            print(\"[DISAGREE] leader payload failed the structural gate\")\n"
     "            return False\n",
     "        if parsed is None:\n            return True\n"),
    ("a validator does not compare its own round",
     "        difference = _first_difference(own, parsed)\n",
     "        difference = \"\"\n"),
    ("facts and scans are not compared",
     "    for key in (\"facts\", \"linked\", \"foreign\", \"markers\", \"hidden\"):\n",
     "    for key in ():\n"),
    ("row status and byte count are not compared",
     "        if a[\"status\"] != b[\"status\"] or a[\"byte_count\"] != b[\"byte_count\"]:\n",
     "        if False:\n"),
    ("finding states are not compared",
     "            if a[\"id\"] != b[\"id\"] or a[\"state\"] != b[\"state\"] or a[\"by\"] != b[\"by\"]:\n",
     "            if False:\n"),
    ("a model error no longer forces rotation",
     "    if leader_text.startswith(ERROR_LLM):\n        return False\n",
     "    if False:\n        return False\n"),
    ("any leader error is agreed with",
     "        if leader_text.startswith(ERROR_TRANSIENT):\n"
     "            return own_text.startswith(ERROR_TRANSIENT)\n        return own_text == leader_text\n",
     "        return True\n"),
    ("a leader error is agreed with without reproducing",
     "    try:\n        reproduce()\n    except gl.vm.UserError as own_err:\n",
     "    try:\n        pass\n    except gl.vm.UserError as own_err:\n"),
    # -- the settlement policy and the agreement --------------------------------------------
    ("policy keys are not an exact set",
     "    if not isinstance(p, dict) or sorted(p.keys()) != sorted(POLICY_KEYS):\n",
     "    if not isinstance(p, dict):\n"),
    ("a partial threshold above the full threshold is accepted",
     "    if p[\"partial_threshold\"] > p[\"full_threshold\"]:\n",
     "    if False:\n"),
    ("policy numbers are not bounded",
     "        if not _int_in(p[key], low, high):\n",
     "        if False:\n"),
    ("terms keys are not an exact set",
     "    if not isinstance(t, dict) or sorted(t.keys()) != sorted(TERMS_KEYS):\n",
     "    if not isinstance(t, dict):\n"),
    ("an instruction in the service description is accepted",
     "    if _injection_hits(t[\"service_description\"]) or _hidden_hits(t[\"service_description\"]):\n",
     "    if False:\n"),
    ("a criterion may name a category the agreement does not source",
     "            if category not in listed:\n",
     "            if False:\n"),
    ("a criterion may be judged on an agent's own words",
     "        if category not in CATEGORIES or category == SELF_ATTESTED:\n",
     "        if category not in CATEGORIES:\n"),
    ("a category may be sourced from anywhere",
     "        if len(prefixes) == 0 and rule[\"category\"] != SELF_ATTESTED:\n",
     "        if False:\n"),
    ("optional enhancements alone are a standard",
     "    if weight == 0:\n",
     "    if False:\n"),
    ("windows are not bounded",
     "        if not _int_in(t[key], MIN_WINDOW, MAX_WINDOW):\n",
     "        if False:\n"),
    ("the price is not bounded",
     "    if not _int_in(t[\"price_atto\"], 1, MAX_PRICE):\n",
     "    if False:\n"),
    ("an agreement may bind a revoked policy",
     "        if str(pv.status) != POLICY_ACTIVE:\n"
     "            self._fail(\"that settlement policy has no active version\")\n",
     "        if False:\n"
     "            self._fail(\"that settlement policy has no active version\")\n"),
    ("an agent may contract with itself",
     "        if seller == buyer:\n",
     "        if False:\n"),
    ("anyone may publish a policy version",
     "        if gl.message.sender_address != latest.owner:\n",
     "        if False:\n"),
    ("anyone may revoke a policy version",
     "        if gl.message.sender_address != pv.owner:\n"
     "            self._fail(\"only the policy owner can revoke a version\")\n",
     "        if False:\n            self._fail(\"only the policy owner can revoke a version\")\n"),
    # -- the adversarial-test engine ----------------------------------------------------------
    ("a case may run twice",
     "        if str(case.status) != CASE_REGISTERED:\n            self._fail(\"case has already run\")\n",
     "        if False:\n            self._fail(\"case has already run\")\n"),
    ("a case passes whatever it observes",
     "        case.passed = outcome[\"verdict\"] == str(case.expected_verdict) and \\\n"
     "            int(case.expected_seller_bps_min) <= outcome[\"seller_bps\"] \\\n"
     "            <= int(case.expected_seller_bps_max)\n",
     "        case.passed = True\n"),
    ("a case ignores the expected share bounds",
     "            int(case.expected_seller_bps_min) <= outcome[\"seller_bps\"] \\\n"
     "            <= int(case.expected_seller_bps_max)\n",
     "            True\n"),
    ("anyone may replay a case onto another version",
     "        if gl.message.sender_address != pv.owner:\n"
     "            self._fail(\"only the policy owner can replay a case\")\n",
     "        if False:\n            self._fail(\"only the policy owner can replay a case\")\n"),
    ("a case may be replayed onto a revoked version",
     "        if str(pv.status) == POLICY_REVOKED:\n            self._fail(\"target version is revoked\")\n",
     "        if False:\n            self._fail(\"target version is revoked\")\n"),
]

# Considered and excluded as equivalent (a second guard makes the first
# unobservable, so no test can tell the mutant from the original):
# - `if level <= low` in _seller_bps: a PARTIALLY_FULFILLED verdict requires
#   level >= partial_threshold, and at the threshold itself the clamped
#   formula already returns the floor, so relaxing the guard to `level < low`
#   changes nothing any test can observe.
# - the `high <= low` arm of the same guard: _parse_policy rejects
#   partial_threshold > full_threshold, and when they are equal the level
#   reaches the FULFILLED branch first, so the arm only exists to make the
#   division safe under a policy the parser cannot produce.
# - `if len(quotes) >= MAX_QUOTES` inside _normalize_answer: the gate rejects
#   any finding carrying more than MAX_QUOTES quotes, so dropping the
#   normalizer's cap is caught by the gate's cap in every path.
# - `if len(items) == 0` in request_adjudication: an adjudication needs a
#   DISPUTED agreement, a dispute needs a delivery, and a delivery names at
#   least one evidence item, so the list is never empty here.
# - the duplicate check in _store_adjudication: ids come from a counter that
#   only ever increases, so no two records can share one.
# - `elif len(asked) == 0` in _plan: the panel's indicators are fixed only when
#   no evidence is eligible, and that case is answered one branch earlier, so
#   there is no round with eligible evidence and nothing to ask.
# - the panel_state comparison in _first_difference: a payload that reaches the
#   comparison has already passed the gate, which ties the panel state to the
#   plan, and any difference in state shows up again in the findings the
#   section comparison walks.
# - the `raise` when the ratified payload fails the gate in _run_round: Direct
#   Mode cannot forge the ratified value (only a leader result, which the
#   validator gates), so the last line of defence against a colluding majority
#   has no offline route. Its clauses are covered by the gate tests.
# - `elif payload["panel_state"] == PANEL_INVALID` in _derive: a panel state of
#   MODEL_OUTPUT_INVALID is only reachable when the plan had questions to ask,
#   which means at least one indicator comes back UNDETERMINED, which reaches
#   INCONCLUSIVE one branch later. The branch states the reason plainly and
#   survives a change to the indicator set; no test can distinguish it today.
#
# Removed rather than excluded: the `payload is None` branch of _derive and its
# `delivered_at == ""` arm were unreachable (both call sites pass a payload
# _run_round produced, and a dispute can only follow a delivery). Dead code
# cannot be killed by a test, so it was deleted instead of being excused here;
# a seller who delivered nothing is settled by claim_stalled_agreement.


def run_suite(workdir: pathlib.Path) -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/direct", "-q", "-x",
         "-p", "no:cacheprovider", "--no-header"],
        cwd=workdir, capture_output=True, text=True)
    return completed.returncode == 0


def check_anchors(source: str) -> int:
    missing = 0
    for name, old, _new in MUTATIONS:
        hits = source.count(old)
        if hits != 1:
            print(f"ANCHOR MISSING ({hits} hits): {name}")
            missing += 1
    return missing


def copy_repo(scratch: pathlib.Path, index: int) -> pathlib.Path:
    work = scratch / ("repo%d" % index)
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".pytest_cache", "deploy", "artifacts", ".data"))
    return work


def main() -> None:
    source = (ROOT / CONTRACT).read_text(encoding="utf-8")
    missing = check_anchors(source)
    print(f"{len(MUTATIONS)} mutations, {missing} anchor problems")
    if "--anchors" in sys.argv:
        sys.exit(0 if missing == 0 else 1)

    only = ""
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].casefold()
    jobs = 1
    if "--jobs" in sys.argv:
        jobs = max(1, int(sys.argv[sys.argv.index("--jobs") + 1]))

    todo = [m for m in MUTATIONS
            if source.count(m[1]) == 1 and (not only or only in m[0].casefold())]
    jobs = min(jobs, max(1, len(todo)))

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="agentguard-mut-"))
    copies = [copy_repo(scratch, i) for i in range(jobs)]

    print("accept-control: unmodified copy must pass ...", flush=True)
    if not run_suite(copies[0]):
        print("CONTROL FAILED: the unmodified suite does not pass; aborting")
        shutil.rmtree(scratch, ignore_errors=True)
        sys.exit(1)
    print(f"control green; {len(todo)} mutations over {jobs} job(s)\n", flush=True)

    results = [None] * len(todo)
    cursor = [0]
    lock = threading.Lock()
    done = [0]

    def worker(work: pathlib.Path) -> None:
        target = work / CONTRACT
        while True:
            with lock:
                i = cursor[0]
                if i >= len(todo):
                    return
                cursor[0] = i + 1
            name, old, new = todo[i]
            target.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            passed = run_suite(work)
            target.write_text(source, encoding="utf-8", newline="\n")
            with lock:
                results[i] = passed
                done[0] += 1
                print(f"  [{done[0]}/{len(todo)}] "
                      f"{'SURVIVED' if passed else 'killed  '}: {name}", flush=True)

    threads = [threading.Thread(target=worker, args=(work,)) for work in copies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    shutil.rmtree(scratch, ignore_errors=True)

    print()
    killed = survived = 0
    for (name, _old, _new), passed in zip(todo, results):
        if passed:
            print(f"SURVIVED: {name}")
            survived += 1
        else:
            print(f"killed:   {name}")
            killed += 1
    print(f"\nmutations: {killed} killed, {survived} survived, {missing} anchor missing")
    sys.exit(0 if survived == 0 and missing == 0 else 1)


if __name__ == "__main__":
    main()
