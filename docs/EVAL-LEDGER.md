# Evaluation ledger: the preregistered calibration lane, as of 2026-09-03

This page records what the preregistered calibration lane behind BankingEnv
has and has not established, in the wording discipline of that lane's own
status file: a result is "established at alpha 0.05", "not established",
"closed by its preregistered falsifier" or "in flight". No stronger label
is used anywhere on this page; predictions are not findings. Every figure is
copied from the lane's reports, named in the footnotes; the reports
themselves are not released.

## 1. Scope and language

- **What was measured.** Task-level work product from one model
  (Claude Opus 5 as the evidence model) answering institution-specific
  operational questions with different reference material pasted into the
  prompt, graded criterion by criterion by two model judges (GLM-5.3
  primary, Claude Opus 5 as a sensitivity judge). No human grading. [6]
- **Where the questions came from.** A private calibration corpus (one
  institution, not released). Two topic areas of that corpus, called loci,
  were used in every run; they are referred to here as locus A and locus B.
  Everything public, including every episode in this repository, is
  synthetic and marked `CLEANROOM_SYNTHETIC`. [6]
- **What this ledger is not.** It is not a result on the forty hash-sealed
  BankingEnv episodes. Those are governed by `cleanroom_eval/assets/
  preregistration.v1.json` and the sealed-set manifests, and no graded
  figure for them is claimed on this page. This repository's own
  `assets/kg_effect/` preregistration series is likewise a separate protocol
  and is not reported here. The lane below is calibration evidence for what
  a BankingEnv task should certify (see `HARBOR-PACKAGING.md`).

### Terms (defined once; taken from the lane's viability read [6])

- **Pack**: a curated rule file per locus, about 8,000 to 12,000 characters,
  each rule carrying a claim, mechanism, operational consequence and
  verbatim quotes from the corpus. **Wrong-locus pack**: another locus's
  pack of identical format, used as a control for "does any pack-shaped text
  help, or only the right content".
- **Unaided (BARE)**: the model with no reference material.
- **Retrieval (RAG)**: corpus passages ranked by word overlap with the
  question, cut to a token budget. **Equal-length** retrieval matches the
  pack's budget; **twice-budget** retrieval matches pack plus retrieval.
- **Quotes-only**: the pack stripped to its verbatim evidence lines.
- **Union**: pack text first, then retrieved passages, pasted together.
- **Sheet**: one written answer; **replicate**: a repeat of the same sheet
  (three per condition per task).
- **Delta**: the difference in mean task score (fraction of rubric criteria
  passed, 0 to 1) between two conditions. **p**: from the exact one-sided
  sign-flip permutation test over paired per-task deltas, zero deltas
  retained; the pass threshold is p below 0.05 per component.
- **Gate**: an automated check on the generated questions before any
  evidence call (Gate A: a cheap model unaided must pass at most 0.20 of
  criteria; Gate B: the evidence model unaided must stay under 0.60).
  **Admission**: a filter keeping only tasks answerable from the source
  text. **Preregistration**: the hash-locked design; **falsifier**: the
  pre-written result that closes a line; **decision tree**: the pre-written
  map from outcomes to conclusions.
- **Intersection-union rule**: a canonical claim passes only if every one
  of its confirmatory contrasts rejects at alpha 0.05, with both loci
  positive under the primary judge and the sensitivity judge agreeing in
  direction.

## 2. Status by run

| Run | Status label | n (tasks) | Canonical claim |
|---|---|---|---|
| T4 v8 | Complete preregistered run; freeze intact. [1] | 10 (2 loci) | NOT passed (C3 failed). |
| T5-v1 | Complete preregistered run; freeze intact. [2] | 9 (2 loci) | NOT passed (C3b and C4 did not reject). |
| T6-v2 | Complete preregistered run; freeze intact. [3] | 20 (2 loci) | NOT passed (U1 did not reject; U2 rejected). |
| T7 Part A | Complete developmental step, existing artifacts only. [4][5] | 18 (T6) and 10 (T5) | No routing signal admitted. |
| T7 Part B (v3) | In flight. [4] | at least 20 admitted, or halt | No result exists as of 2026-09-03. |

Three earlier runs precede T4. The lane's status file labels them as a valid
falsifier of a generalized rubric, an institution-bound exclusivity and
delivery-rate measurement (not uplift), and an informative but not canonical
developmental run whose instrument was repaired during the sequence. None is
a canonical result and they are not reported here. [1]

## 3. T4 v8: task-level uplift exists; superiority over raw source not shown

Claim under test: a compact doctrine representation improves task-level work
product on independently constructed, institution-specific problems relative
to the same model unaided, and its effect is not explained solely by
additional tokens, verbatim fact delivery, rubric leakage or grading
circularity. [2]

| Contrast (pack minus ...) | Delta | p | Standing |
|---|---|---|---|
| C1 unaided | +0.408 | 0.0020 | established at alpha 0.05 |
| C2 wrong-locus pack | +0.467 | 0.0078 | established at alpha 0.05 |
| C3 matched-length raw excerpts | +0.108 | 0.256 | not established; interval spans zero |
| C4 quotes-only | +0.367 | 0.0059 | VOID (erratum) |

Both judges agreed on 95.8 percent of criterion verdicts; both loci were
directionally positive; one refusal was retried successfully; no judge output
was missing and no task excluded. Locus heterogeneity was strong (pack minus
unaided +0.65 on one locus and +0.17 on the other). [1]

**Erratum (2026-09-02).** The T4 quotes-only context was empty for both loci
(a format mismatch between the quotes filter and the pack writer), so the
quotes-only prompts were byte-identical to the unaided prompts. C4 was a
second pack-minus-unaided estimate, not a verbatim-delivery control, and is
void. T4's gate outcome is unchanged (it failed on C3); its supported
contrasts are C1 and C2, two of three valid contrasts, not three of four. Any
external text that repeats "three of four" for T4 should be corrected. [1][2]

## 4. T5-v1: the compact-representation line closes

Changes from T4, all preregistered: the pack repaired with 16 gap rules the
owner adjudicated; a question-keyed equal-length retrieval arm (C3b) replacing
T4's raw-excerpt control as the confirmatory comparison, with the T4 oracle
window demoted to a descriptive control (C3a); fresh questions from the same
two loci. n=9: one task was excluded under the frozen missing-data policy
after nine persistent API refusals on its unaided replicates. [2]

| Contrast (pack minus ...) | Delta | p | 95 percent BCa interval | Sensitivity judge | Standing |
|---|---|---|---|---|---|
| C1 unaided | +0.537 | 0.0059 | [0.287, 0.732] | +0.556, p=0.0039 | established at alpha 0.05 |
| C2 wrong-locus pack | +0.593 | 0.0039 | [0.306, 0.815] | +0.620, p=0.0020 | established at alpha 0.05 |
| C3b equal-length retrieval (confirmatory) | +0.269 | 0.152 | [-0.194, 0.639] | +0.269, p=0.141 | not established |
| C4 quotes-only | +0.148 | 0.172 | [-0.037, 0.417] | +0.167, p=0.125 | not established |
| C3a oracle raw window (descriptive) | +0.046 | 0.461 | [-0.102, 0.389] | +0.046, p=0.469 | descriptive; does not gate |

Per-locus pack minus unaided: +0.450 and +0.646, both positive. Judge
agreement 686 of 708 criterion verdicts (96.9 percent), Cohen's kappa 0.938.
Both judges returned the same verdict on every contrast. [2]

**Preregistered falsifier, applied as written:** C3b did not reject, so even
against an equal-token retrieval baseline the repaired pack shows no
advantage; the compact-representation line (the idea that a short written-up
rule set is worth more than the documents it came from) is closed on this
evidence. C4 also did not reject, so the remaining position rests on C1 and
C2 only: the pack beats the unaided model and beats a wrong-locus pack; it is
not shown to beat its own verbatim evidence lines or question-keyed retrieval
from the corpus. [2]

Disclosures carried by the report: a provider spend-limit pause mid-run with
a same-version, manifest-verified resume (no code, prompt, question, context
or rubric changed); the quotes arm was partial (it held only 16 to 20 percent
of the pack's characters, which is generous to the pack, not against it); the
task exclusion is not conservative for the pack's effect sizes; coverage
between pack and retrieval was largely complementary (on 6 of 10 tasks one
scored at least 0.83 while the other scored at most 0.25), a descriptive
reading only. [2]

## 5. T6-v2: pack plus retrieval against retrieval alone

Claim under test: on twenty fresh tasks from the two loci, the correct-locus
pack prepended to deterministic question-keyed retrieval produces better
work product than twice-budget retrieval alone (U1), and better work product
than an equal-budget wrong-locus pack combined with the identical retrieved
material (U2). n=20; all 420 sheets generated, 0 refusals, 0 missing sheets.
[3]

| Contrast (union minus ...) | Delta | p | 95 percent BCa interval | Zero deltas | Per-locus (A, B) | Sensitivity judge (n=19) | Standing |
|---|---|---|---|---|---|---|---|
| U1 twice-budget retrieval | +0.158 | 0.061 | [-0.004, 0.358] | 8 | +0.267, +0.050 | +0.184, p=0.055 | not established |
| U2 wrong-locus pack plus same retrieval | +0.179 | 0.041 | [0.017, 0.379] | 11 | +0.275, +0.083 | +0.197, p=0.046 | established at alpha 0.05 |

Descriptive contrasts (same statistics; never gate): [3]

| Contrast | Delta | p | 95 percent BCa interval | Per-locus (A, B) |
|---|---|---|---|---|
| U3 union minus pack | +0.104 | 0.042 | [0.017, 0.242] | -0.025, +0.233 |
| C1r pack minus unaided (third replication) | +0.454 | 0.00003 | [0.288, 0.625] | +0.500, +0.408 |
| C3b-r pack minus equal-length retrieval | +0.100 | 0.225 | [-0.129, 0.358] | +0.350, -0.150 |
| C4f pack minus fixed quotes-only (first valid quotes control) | +0.063 | 0.206 | [-0.033, 0.225] | +0.192, -0.067 |

Gate results: Gate A 0.175 (locus A) and 0.025 (locus B) against a 0.20
ceiling; Gate B 0.200 and 0.0125 against 0.60; no halt. Judge agreement on
the 399 dual-graded sheets: 1,536 of 1,596 criterion verdicts (96.2
percent), kappa 0.92. Doubling the retrieval budget changed the score on
five of twenty tasks (mean +0.046), so the union's margin over twice-budget
retrieval is not a length effect; that is an inference from the matrix, not
a test. Two of twenty tasks scored zero in every arm (floor tasks); under the
exact test their zero deltas are neutral for p but they diluted the mean and
spent two slots. [3]

**Preregistered falsifier, applied as written:** U1 not supported, so
pack-as-context authoring has no demonstrated incremental product value over
equal-budget fair retrieval on these loci. Standalone pack authoring stops as
a product activity; curation continues for retrieval, evidence selection,
routing and adjudication. U2 did reject, so the union's advantage over a
wrong-locus pack plus the same retrieval is supported at the preregistered
threshold; that does not rescue the claim, which required both. [3]

Disclosures carried by the report: a v1 of this run halted before any
evidence call (one judge call over 36 to 40 criteria exhausted the judge's
token budget; v2 judges per question); four provider spend-limit pauses with
same-version, manifest-verified resumes and no missing sheet; the
sensitivity judge is missing on one locus-A task (its 21 judge calls were the
last in queue when the limit closed), so the sensitivity set is n=19 with all
direction conditions met; the equal-length retrieval arm under-filled its
budget on two questions because of one very long corpus line, which is
conservative for U1 on one of them. [3]

## 6. Closed lines, open claim, routing result

**Closed by preregistered falsifier.**

1. Compact representation (a curated rule set beats the documents it came
   from): closed at T5 (C3b). [2]
2. Standalone pack authoring as a product activity: stopped at T6 (U1). [3]
3. Routing at the cheap and probe-based signal level: closed at T7 Part A
   (below). [4][5]

**Replicated three times, scoped to two loci of one corpus and model
judges only.** Pack over unaided: T4 +0.408, T5 +0.537, T6 +0.454. Content
specificity, tested against a wrong-locus pack of identical format: T4
+0.467, T5 +0.593, and in union form at T6 +0.179. What this supports is
narrower than "curated knowledge beats the documents": curated evidence
beats the unaided model and beats the wrong evidence, and the gain depends
on the content being the right content. [1][2][3][6]

**Union claim status.** Not passed at T6 (U1 p=0.061 against alpha 0.05,
interval touching zero, positive at both loci and under both judges). T7 is
its terminal test under a two-strikes rule (section 7). No result exists
yet. [3][4]

**Routing-signal result (T7 Part A, developmental, existing artifacts
only).** A router would choose per question between retrieval alone and
pack plus retrieval using a signal computable before answering. Three cheap
pre-answer signals (lexical retrieval coverage of the question, abstention
rate in the retrieval-only answer, pack coverage of the question) were rejected offline
on T5 and T6 artifacts: the best in-sample router gave +0.108 against
always-union at +0.158 over the twenty T6 tasks. Two model probes were then
evaluated on T6's 18 admitted tasks (the two floor tasks excluded
retrospectively) and T5's 10 tasks, with no rubric shown to either probe,
under an admission rule fixed before they ran (beat always-union by at least
+0.05 mean delta, route at least three tasks each way, no sign reversal on
T5). [4][5]

| Probe | Best threshold | Simulated routed mean | Always-union on the same tasks | Gain | Routed (union / retrieval) | T5 check | Admitted |
|---|---|---|---|---|---|---|---|
| S4 self-coverage (fraction of question sub-parts the retrieved material does not cover) | 0.667 | +0.208 | +0.176 | +0.032 | 6 / 12 | +0.175, no reversal | No (below +0.05) |
| S5 disagreement (contradictions between two retrieval-only answers) | 0 | +0.106 | +0.176 | -0.069 | 14 / 4 | +0.075 | No |

The oracle router ceiling on the same 18 tasks (picking the better arm on
every task with the answer key) is +0.250, so even a perfect signal would add
about +0.07 over always-union; routing is bounded whatever the signal. 51 of
56 probe calls completed; five task-probe pairs carry a missing signal.
Consequence per the frozen decision tree: no routed arm is run in T7; S4's
near-miss is recorded as a descriptive observation only. [4][5][6]

## 7. T7: design of the terminal test (in flight)

T7 is preregistered (v3, frozen at a recorded protocol commit after Part A
completed and its preflight passed) and running as of 2026-09-03. Nothing
below is a result. [4]

- **Estimand (section 2, verbatim).** "T7 estimates union uplift over
  retrieval for institution-specific tasks demonstrably answerable from the
  source corpus, not for arbitrary generated tasks." Conditioning on oracle
  answerability changes the estimand from T6's, and this is the intended
  change; every figure in the report is scoped to admitted tasks.
- **Questions and gates (section 4).** Two loci, fifteen questions per
  locus from the frozen generator, each generation persisted before gating.
  Gate A may trigger at most one regeneration and conditions only on
  cheap-model unaided discrimination, never on retrieval coverage, the
  evidence model or any arm output; a second failure halts. Gate B is
  halt-only. Questions are frozen to disk before any admission, retrieval,
  probe or evidence call.
- **Oracle admission gate (section 4, arm-independent).** For every frozen
  task one ORACLE sheet is written by the evidence model whose context is
  exactly the raw-source slice the generator saw (the first 100,000
  characters of the locus window, the same constant in both places). The
  sheet is graded by the primary judge against the frozen rubric; a task is
  admitted iff at least one criterion passes. No pack, retrieval or union
  output exists when admission is fixed. Admission outcomes, oracle
  scores and oracle context hashes are written to the freeze manifest before
  retrieval is built; tasks not admitted are listed and excluded from every
  contrast. Fewer than 20 admitted tasks halts the run with a report, so the
  terminal test cannot run underpowered by accident.
- **Arms (section 4).** Unaided; twice-budget retrieval; union (pack first);
  wrong-locus union; ORACLE (one sheet per task, graded by both judges,
  descriptive only). Three replicates, interleaved under a fixed seed.
  Budgets, nested retrieval, wrong-pack truncation, hashing, the refusal
  rule (a persistent policy refusal scores zero), judges and resume
  semantics are byte-identical to T6-v2. The pack-alone, equal-length
  retrieval and quotes-only arms are not run; their questions were answered
  in T5 and T6.
- **Contrasts and gate (section 5).** Confirmatory: U1 union minus
  twice-budget retrieval greater than 0; U2 union minus wrong-locus union
  greater than 0. Descriptive, never gate: O1 oracle minus retrieval; B1
  union minus unaided. Exact one-sided sign-flip permutation on paired task
  deltas, alpha 0.05 per component, zero deltas retained, both loci positive
  on both components under the primary judge, sensitivity judge pooled
  direction positive with no locus-level reversal. The union claim passes
  only if U1 and U2 both pass; no multiplicity correction. Routed contrasts
  (R1, R2, R3) do not exist because Part A admitted no signal.
- **Two strikes (section 6, verbatim in substance).** T7 is the terminal
  test of U1 on these loci. If U1 fails here, under the oracle admission gate
  and the larger sample, pack-as-context authoring stops as a product thesis
  for these loci and the union line is not re-run under any future
  preregistration; the response is not parameter tuning.
- **Frozen decision tree (section 7).** Part A admits no signal: routing
  closed at the cheap and probe-based level (reached). U1 fails: union and
  pack-as-context line closed on these loci. U1 passes and U2 fails: a
  generic context or scaffolding effect, not institution-specific value.
  U1 and U2 pass: the union thesis survives on these loci and the next
  experiment is untouched-locus replication, not another optimisation run.
  The runner writes the branch reached into the report.
- **Planning estimate, not a guarantee.** With the effect distribution T6
  measured, the decisive comparison has about a 50 percent chance of passing
  at twenty admitted tasks and about 70 percent at thirty. [6]
- **Two prior versions halted before any scored answer.** v1 at Gate A (the
  generated questions were too answerable by a cheap model without
  documents) and v2 at admission (its four-slice oracle window measured which
  questions fell in the sampled slices, not answerability, which mismatched
  the estimand). Both were defects in the measuring apparatus caught by
  automated checks before any evidence call; their question sets are void
  and preserved separately. v3 changed only the oracle context (the
  generator's own source slice), the under-20 halt and a stray-artifact
  guard. [4][6]

## 8. What the lane licenses, and its limits

Licensed on this evidence, scoped to two loci of one private corpus, model
judges only: a curated pack raises task-level pass rate over the unaided
model and over a wrong-locus pack (three runs); the pack prepended to
retrieval beats a wrong-locus pack prepended to the same retrieval (T6 U2).
Not shown: an advantage over question-keyed retrieval from the corpus at
equal length (T5 C3b, T6 C3b-r), over the pack's own verbatim evidence (T5
C4, T6 C4f), or over twice-budget retrieval alone at the preregistered
threshold (T6 U1). [2][3]

Limits carried by every figure above: [6]

1. Effect sizes are small relative to task-to-task variation (the pack's
   help ranged from +1.0 to -0.5 across tasks), so a twenty-task mean is
   unstable.
2. The measuring apparatus is sensitive to its settings: question sets of
   fifteen came in at 36, 22 and 16 percent answerable by the cheap model
   unaided against a 20 percent ceiling, each generation being a fresh
   random draw; pre-run gates caught each failure at the cost of a new frozen
   version.
3. External validity is unmeasured: one institution, two loci, model judges,
   no human grading. The loci disagree: on locus A pack plus retrieval beats
   retrieval by +0.27; on locus B retrieval already answers most tasks and
   the pack adds +0.05 (T6 per-locus U1). [3]

Commercial reading recorded by the lane, not a finding of any run: the claim
the evidence supports is narrower than "curated institutional knowledge beats
the documents"; what is supported three times over is curation as evidence
selection and adjudication inside a retrieval product, and the packaging
direction that follows is environments, benchmarks and adjudication rather
than a standalone knowledge-pack product. [6]

## Footnotes: sources (private lane reports, not released)

1. `RESULTS-STATUS.md`, owner directive of 2026-09-01 with the T4 v8, T5-v1
   and T6-v2 status blocks and the T4 C4 erratum of 2026-09-02.
2. `T5-REPORT.md`, T5-v1 complete report (sections 1 to 7).
3. `T6-REPORT.md`, T6-v2 complete report (sections 1 to 7).
4. `PREREG-T7.md`, v3, sections 2 (estimand), 3 (Part A), 4 (Part B
   design), 5 (contrasts and gates), 6 (two strikes), 7 (decision tree), 11
   and 12 (v1 and v2 halts).
5. `PART-A-RESULTS.md`, T7 Part A probe results.
6. Viability read of 2 to 3 September 2026 (private), the version with
   definitions; source of the glossary, the planning estimate, the
   apparatus-sensitivity figures and the commercial reading.
