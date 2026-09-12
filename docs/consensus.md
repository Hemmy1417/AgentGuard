# Consensus

One consensus round per adjudication, readjudication or adversarial case, run
with `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`. The leader proposes a
payload; every validator reproduces the round from its own fetches and its own
model call, gates the leader's payload against its own verified bytes, and
compares the fields that decide the outcome.

## What is asked of the model, and what is not

The panel is asked only what a reader of the evidence can answer:

- for each still-open acceptance criterion: SATISFIED, NOT_SATISFIED or
  UNVERIFIABLE, with quotes;
- for each of six indicators: PRESENT, ABSENT or UNDETERMINED, with quotes -
  `EVIDENCE_MANIPULATION`, `BUYER_WITHHELD_INPUT`,
  `EXTERNAL_DEPENDENCY_FAILED`, `SELLER_SCOPE_CHANGE`, `BUYER_CRITERIA_CHANGE`,
  `INSTRUCTION_INJECTION`.

It is never asked for an amount, a percentage, a fault level or a verdict. The
prompt says so in its first paragraph, and the payload has no field for one:
`seller_bps`, `payment_allocation_atto` and `verdict` are computed by
`_derive`, `_seller_bps` and `_split` from the agreed findings. A model that
invents those keys changes nothing - the gate rejects any payload whose key set
is not exactly `PAYLOAD_KEYS`.

The prompt frames the whole data block as untrusted: statements are claims, a
declared category and issuer are the submitter's claims, and only
`facts_verified_by_code` - integers code read from hash-verified bytes - are
authoritative. It states that the frozen criteria are the whole standard, and
that anything either party said afterwards adds nothing.

An item code has excluded (hidden text, an injection marker, another
agreement's record, stale, duplicated or reused) is listed with
`excluded_by_code: true` and without its text (`EXCLUDED_TEXT`). Nothing in it
may support an answer, and its text is what an attacker wrote to be read. When
the panel was shown it, models reported the hidden instruction they found
there - a finding whose only quotes came from an item that cannot be quoted -
and the round fell to UNDETERMINED or split on that question.

An indicator the panel cannot decide is UNDETERMINED, and an undecided
question holds the escrow only when its answer could have changed the verdict -
the five in `OUTCOME_INDICATORS`. `BUYER_CRITERIA_CHANGE` is not among them:
it records fault, not money.

Each question has exactly one home. A criterion that is not met is reported on
that criterion, never as an indicator; a disagreement between two items is a
criterion matter, while fabrication visible *inside* one item is
`EVIDENCE_MANIPULATION`. The partition is deliberate: overlapping questions are
what split a panel in an earlier build of this author's, with different models
recording the same fact in different places and every round disagreeing.

## The equivalence rule

`EQUIVALENCE_STATEMENT` is stored in the contract and returned by
`get_config`:

> A validator ratifies the leader only if, after re-fetching and hash-verifying
> every allowed evidence item itself: the leader payload passes the structural
> gate (exact keys and types, known enums, code-decided fields recomputed from
> the rows, facts and scans, every quote's words present in the validator's own
> verified bytes); and every row's status and byte count, every structured
> fact, the agreement link, injection and hidden-text scans, the panel state
> and reason, and the state and deciding layer of every criterion and indicator
> equal its own - for an indicator that records fault and never moves money,
> whether it is PRESENT. The fulfillment level, verdict, fault levels, seller
> payment and buyer refund are then computed by code from those agreed fields,
> so validators agree on them by construction, and no model output reaches an
> amount. Notes and quote choice are grounded, never compared.

Two properties follow. **Consensus is required on everything with a
consequence** - a criterion's state, an indicator's state, which layer decided
it, and every byte-level fact under them. **Consensus is not required on what
decides nothing** - the note a model wrote and which of several valid quotes it
chose differ between models, so comparing them would only manufacture
disagreement.

The one indicator where those two meet is `BUYER_CRITERIA_CHANGE`, the only
member of `FAULT_ONLY_INDICATORS`. It never changes the verdict or the split
(`OUTCOME_INDICATORS` leaves it out), and the buyer's fault level follows
PRESENT alone, so ABSENT and UNDETERMINED have exactly the same consequence.
Validators compare whether it is PRESENT (`_same_reading`). On the live network
ABSENT against UNDETERMINED on that question was six of 38 validator
disagreements, and in diagnostic run four the whole reason a round of A15 stored
nothing.

## The structural gate

`_parse_payload` runs twice: on every validator, against that node's own texts,
and again in the contract on the ratified payload before anything is stored or
paid. It rejects a payload that:

- is not JSON, is over 300 000 characters, or whose key set is not exactly
  `PAYLOAD_KEYS`;
- carries a different schema, subject, round, clock, `terms_hash` or
  `evidence_commitment` - so a payload from another round or another agreement
  cannot be replayed;
- has a row list that does not line up with the agreement's items, a row status
  outside the enum, a `NOT_ALLOWED` status that disagrees with the allowlist, a
  byte count for bytes that did not verify, or a `TOO_LARGE` status that
  disagrees with its own byte count;
- carries structured facts for items that were not examined, or a fact that
  fails revalidation against its category's schema;
- carries link, foreign-agreement, marker or hidden-text lists that do not
  match what this node's own scan produced;
- disagrees with this node's own `_plan` about whether the panel could be
  convened, or about any of the six code indicators;
- carries a finding whose shape, author, state vocabulary, evidence ids, quote
  count or quote length breaks the rules;
- carries a quote whose words are not present, in order, in **this node's own**
  verified bytes for the cited item;
- carries a decided criterion with no surviving quote, or an indicator PRESENT
  whose support does not meet its quote rule.

That last rule is the interesting one. Each indicator declares a minimum number
of distinct quoted items and, when the finding favours one agent, that at least
one quoted item must not have been written by that agent. So a seller's own
message cannot establish that the buyer withheld access - but a buyer's own
message admitting it can, because an admission against interest comes from the
other side. The rule replaced a blanket exclusion of self-attested items, which
had the perverse effect of throwing away the best evidence a party can give.

## Quote grounding

`_quote_grounded` tokenizes both the quote and the source into lowercase
alphanumeric words. A quote is split at each ellipsis into parts, found in
order. Each part is sought first as one contiguous run of the document's
words, wherever its line breaks fall: a verbatim copy of a wrapped paragraph
keeps the document's own breaks, and its last line may be a single word. A
part that does not run contiguously is read as lines joined from different
places - each line found in order, lines that follow each other in the
document forming one run. Every run needs at least two words. Nothing the
document does not say can ground, and nothing out of the document's order can.

A model reading a structured document often reflows several of its lines onto
one and joins them with a comma, which is the claim an ellipsis makes. A quote
that does not ground as written and contains `, ` is tried once more with each
`, ` read as an ellipsis, under exactly the same rule.

A quote over the 240-character cap is tried at successively shorter cuts: at
the last word boundary inside the cap, then back one line, part or reflowed
item at a time. The cut is never what loses a quote that grounds as written;
`test_cutting_to_the_cap_never_loses_a_quote_that_grounds` checks that over
every line of four fixture documents, shifted a word at a time.

Both rules came from the live network, where the deployment before this one
refused quotes that were copied exactly. It read every line break as an
elision, so a verbatim quote of a paragraph whose document wrapped its last
word onto a line of its own ended in a one-word fragment: in case A16's rounds
four validators quoted the same sentence of the delivery summary that way and
lost it, and for one of them it was the only support for its reading of
criterion C3. It also cut an over-long quote only once, and a cut that stranded
one word after a line break dropped a quote of the method report that grounded
as written - which is what put one validator in disagreement with the leader
over C3 in case A15's round, and another in a diagnostic round of the baseline.
Neither refusal can ground anything the document does not say; both only
manufactured disagreement.

If a quote fails to ground, it is dropped; a criterion left with no quote is
downgraded to UNVERIFIABLE and an indicator to UNDETERMINED - and the node
prints `[DOWNGRADE] ...` with the raw quotes, so a disagreement explains itself
in that node's stdout.

## When the panel is not convened

`_plan` decides this before any model is called, and both the leader and every
validator compute it identically:

| `panel_reason` | Meaning |
|---|---|
| `EVIDENCE_NOT_EXAMINED` | some allowed item was not examined; the round cannot be about the evidence, so no model is asked about it |
| `NO_EXAMINED_EVIDENCE` | every examined item is tainted; there is nothing a panel could read |
| `NOTHING_TO_ASSESS` | code already answered every criterion and indicator. A guard rather than a state a round reaches today: the panel's indicators are fixed only when no evidence is eligible, and that case is answered one branch earlier |

A skipped panel leaves its subjects UNVERIFIABLE or UNDETERMINED, which holds
the escrow rather than settling on a guess. `MODEL_OUTPUT_INVALID` is the
fourth state: the model answered something that is not an answer, which also
holds.

## Errors

| Prefix | Used for | Validator behaviour |
|---|---|---|
| `[EXPECTED]` | business rules the contract enforces | must match the leader's message exactly |
| `[EXTERNAL]` | a deterministic external refusal | must match exactly |
| `[TRANSIENT]` | an unreadable clock, a model call that failed | agrees if its own attempt is also transient |
| `[LLM_ERROR]` | a ratified payload that fails the gate | always disagree, forcing rotation |

A validator that raises propagates, which counts as disagreement. A leader
error is never taken on trust: the validator reproduces the round first and
only then compares.

A round that cannot reach consensus costs nothing but time. The transaction
fails, no adjudication is stored, the agreement stays DISPUTED and the escrow
does not move - and anyone may ask again, with a different panel. That is the
deliberate failure mode: a split panel never settles, and never strands.

## Direct Mode and what it proves

`genlayer-test`'s direct runner exercises validator logic as well as the
leader: `direct_vm.run_validator(leader_result=...)` replays the contract's
`validator_fn` with the mocks the test chooses, so the suite can hand a
validator a forged payload, a payload from another round, a quote that does not
ground, or bytes that differ from the leader's and assert the vote. Those tests
live in `tests/direct/test_consensus_equivalence.py`.

What Direct Mode cannot show is model diversity: real StudioNet validators span
several model families, and two of them can read the same evidence differently.
That is what the panel is for, and the appeal path is the answer when a round
comes back INCONCLUSIVE. The live run in `deploy/` is where the real panel is
exercised.

Nor does a minority disagreement end a round. GenLayer's own consensus decides
that: in one recorded diagnostic round three validators ratified the leader
while two read a criterion as NOT_SATISFIED where the leader had UNVERIFIABLE,
and the round was accepted on the majority. A criterion's state is therefore
what a majority of the panel agreed, not what every member would have said -
and the rest of this design assumes exactly that much and no more: grounded
quotes, a gate every node applies alone, and code that turns agreed findings
into money.
