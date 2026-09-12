# Evidence policy

Every claim in an AgentGuard dispute is backed by bytes that each validator
fetched and hashed itself, or it is not used. Nothing an agent says is a fact.

## Categories

| Category | Structured | What it is | What it cannot show |
|---|---|---|---|
| `DELIVERABLE` | no | the delivered artifact as served at its committed location | that it is useful - that is judged |
| `EXECUTION_LOG` | yes | a run log the executing party produced | its own truthfulness |
| `API_RECEIPT` | yes | a receipt from a named endpoint | that the result was correct |
| `TEST_OUTPUT` | yes | test results as reported | that the tests are meaningful |
| `USAGE_RECORD` | yes | usage as recorded by an issuer for a period | anything outside the period |
| `THIRD_PARTY_RECORD` | no | a record neither agent wrote | a numeric fact; it is read by the panel |
| `ACCEPTANCE_MESSAGE` | no | a party's acceptance or rejection message | a fact about the work |
| `AGENT_MESSAGE` | no | one agent's own words, self-attested | anything; it is never a fact and never decides a criterion |

Structured items are parsed by code into integers (`_structured_facts`). A
float, a boolean, a string, a negative number, a run that finishes before it
starts, or a test report whose parts do not sum makes the item UNPARSEABLE -
never a fact, and never a zero.

## The source allowlist

Each agreement lists, per category, up to four `trusted_prefixes`: full
`https://host/path/` prefixes ending in `/` with no query. `_provenance`
decides admission for one item:

- a category the agreement does not source at all: **not allowed** - never
  fetched;
- a category it sources, from a location under one of that category's frozen
  prefixes: **allowed and trusted**;
- a category it sources, from anywhere else: **not allowed**;
- `AGENT_MESSAGE`: **allowed from anywhere, never trusted** - an agent's own
  words are admissible as words, and can never satisfy a criterion.

Prefix matching is exact string prefixing on the canonical URL, and prefixes
must end in `/`, so `.../sources/delivery-mirror/` is not
`.../sources/delivery/`. Both were frozen at assent, so neither agent can add a
source after seeing the evidence.

## URL admission

`_url_parts` is defence in depth, not an SSRF boundary - runtime egress control
remains the real boundary. A committed location must be: `https`, printable
ASCII with no whitespace or backslashes, no fragment, no credentials, no port
other than 443, a fully qualified DNS name (never an IP literal in any form,
never `localhost`, `.local`, `.internal`, `.home.arpa` or `.lan`), and a path
with no dot-segments, no empty segments and no percent-encoded separators
(`%2e`, `%2f`, `%5c`). The canonical form (lowercased host, no default port) is
what is stored, hashed into the evidence commitment and prefix-matched.

## Commitment and retrieval

`submit_evidence` records a category, a canonical URL, a sha256 of the exact
bytes, an issuer label and a description. Either party may commit; the same
bytes or the same location cannot be committed twice to one agreement, and at
most 14 items in total. Nothing is fetched at commitment time.

At adjudication, every node runs `_fetch_row` for each item:

```text
not allowed            -> NOT_ALLOWED   (no request is made at all)
request fails / non-2xx/ empty body     -> UNAVAILABLE
sha256(body) != committed digest        -> HASH_MISMATCH
body larger than 8000 bytes             -> TOO_LARGE   (byte count recorded)
not UTF-8, blank, or a structured item
that breaks its schema                  -> UNPARSEABLE (byte count recorded)
otherwise                               -> EXAMINED
```

The hash is checked **before** anything reads the body, so unverified bytes are
never parsed, never scanned and never shown to a model. A byte count is
recorded only for bytes that verified, which every honest node holds
identically - it is part of the equivalence comparison.

## What code decides about an item

Six code indicators, each derived from bytes the node hashed itself:

| Indicator | Present when |
|---|---|
| `EVIDENCE_UNLINKED` | a structured item names another agreement, or a text item (except a `DELIVERABLE`) carries some other agreement's id |
| `DUPLICATE_EVIDENCE` | two items in this agreement have the same sha256 |
| `HIDDEN_TEXT` | zero-width or bidirectional control characters, or CSS that hides text (`display:none`, `opacity:0`, ...) |
| `INJECTION_MARKER` | one of the literal marker phrases appears in the normalized text |
| `DEADLINE_MISSED` | delivery arrived after the deadline plus the cure period |
| `STALE_EVIDENCE` | a structured item's `as_of` is older than the policy's maximum age |

Five of the six taint the items they name: a tainted item may not satisfy a
criterion, whoever submitted it, and it is not shown to the panel as usable
evidence. `DEADLINE_MISSED` is about the delivery, not an item, so it taints
nothing. The registry adds `CROSS_AGREEMENT_REUSE`, which taints as well.

A `DELIVERABLE` is deliberately exempt from the cross-agreement scan: the same
artifact can honestly be sold to two buyers, and flagging that would punish a
legitimate resale. A job's paperwork - an acceptance message, a third party's
record - belongs to one job, and reusing it is exactly attack 10.

Each indicator is per-item and fails closed: PRESENT on any examined item that
shows it; ABSENT only once every item it applies to was examined; UNDETERMINED
while one is unread.

## Receipts

Every adjudication record carries one receipt per evidence item
(`_receipts`), with the fields the brief asks for:

| Field | Value |
|---|---|
| `evidence_id`, `record_id` | the stable id in this round, and the stored item |
| `source_type` | the declared category |
| `submitted_by` | buyer or seller |
| `source_locator` | the canonical URL |
| `retrieved_at` | the round's clock, when a request was made |
| `content_hash`, `hash_verified` | the committed digest, and whether the bytes matched |
| `source_identity` | the trusted prefix it matched, if any |
| `source_reachable`, `status` | reachability and the row status above |
| `relevance_status` | `LINKED` / `OTHER_AGREEMENT` for structured items, `NAMES_AGREEMENT` / `UNSTATED` for text, `NOT_ASSESSED` when unread |
| `authenticity_status` | `ACCEPTED`, `EXCLUDED` (tainted) or `NOT_ASSESSED` |
| `freshness_status` | the item's `as_of`, or `UNDATED` |
| `conflict_status` | whether a finding quoted it |
| `counted` | whether it could support a finding at all |
| `limitations` | the standing caveat for its category |

A receipt is written for every item, including items that were never fetched;
the record shows what was refused as plainly as what was read.
