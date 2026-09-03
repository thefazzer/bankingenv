# Packaging BankingEnv episodes as harbor tasks

Design note, 2026-09-03. It describes how a sealed BankingEnv episode maps
to a harbor task directory of the kind Mercor's ApexAgents-SkyRL recipe
consumes, the held-out split policy, and the per-task certificates that a
task must carry before it counts. `scripts/export_harbor.py` is the script
skeleton that writes the layout from this repository's sealed assets; it has
a dry-run mode, invents no task content and issues no certificate. Nothing on
this page is a training or scoring result.

## 1. What the recipe consumes

The recipe's README was fetched on 2026-09-03 (network was available) and
harbor's task-structure documentation alongside it; the layout below follows
both. [1][2] The recipe's own task data cannot be open-sourced for licence
reasons, so its README documents the format instead, and this note relies on
that description rather than on an inspected task.

Training consumes a HuggingFace dataset of prebuilt harbor task directories:
parquet shards with two columns, `path` (the task directory name) and
`task_binary` (a gzip-compressed tar of the directory). Extracting a row
yields a standard harbor task directory: [1]

```
<task-dir>/
  instruction.md          the prompt the agent sees
  task.toml               harbor task config: agent and verifier timeouts,
                          [verifier.env] key forwarding, resources
  archipelago.json        recipe-specific metadata read by the generator
  environment/Dockerfile  placeholder; the real environment is a prebuilt image
  tests/                  the verifier; never mounted for the agent
    test.sh               entrypoint harbor runs in-sandbox after the agent
    grade.py              drives the grading runner, emits the reward
    verifiers.json        rubric criteria (LLM-judged), hidden from the agent
    golden_responses.json reference answers for the rubrics
    runner/               vendored grading runner, pinned at a commit
```

Two facts about that layout shape everything below. First, tasks are grouped
into worlds (simulated companies with documents, apps and tool servers) and
environments are built per world, not per task: one image per world,
referenced by every task in it, with the per-task Dockerfile a placeholder.
Second, the grading code ships inside every task, so training needs no
checkout of the grader. [1]

Harbor itself fixes the rest: `instruction.md`, `task.toml`, an optional
`solution/solve.sh` for an oracle agent, and `tests/test.sh`, which is
copied to `/tests` at run time and must leave a reward at
`/logs/verifier/reward.txt` (a single number) or `/logs/verifier/reward.json`
(named numeric metrics; read by default, with `reward.txt` as the fallback).
A verifier may run in a separate environment (`[verifier]
environment_mode = "separate"`), in which case harbor builds the verifier
image from `tests/` and the agent never sees it; the agent's
`/logs/agent/trajectory.json` reaches that verifier when it is listed in the
task's `artifacts` field, the documented pattern for a trajectory-grading
verifier. [2]

## 2. What BankingEnv already has

This repository holds the pieces in a different arrangement: [3]

- **Sealed episodes** (`cleanroom_eval/assets/episodes/`, forty in set v1,
  and `episodes_v2/`, forty in set v2; eight operational families with five
  variants each). An episode is the evaluator's record and carries the
  oracle: the terminal state, every scripted mutation, expected receipts,
  reward traps, adversarial mutations and evidence challenges.
- **Task cards** (`*.task.v1.json`, derived by
  `cleanroom_eval/episode_contract.py`): the agent-facing statement of the
  work, actors, tracked objects, surfaces, actions, deliverables, the
  deterministic check list and the disclosure barrier. `verify_contract`
  proves that a card agrees with its episode and carries none of the oracle
  fields.
- **The observable boundary** (`cleanroom_corpus/eval_adapters.py`,
  `EvaluationSession` in free mode): six tool surfaces that accept versioned,
  authorised, evidence-grounded requests and reject everything else without
  changing state. The agent never reads hidden state.
- **Deterministic graders** (`cleanroom_eval/contract.py`,
  `evaluate_episode`): chronology, referential integrity, authorisation,
  version monotonicity, idempotency, per-currency ledger conservation,
  evidence presence and sufficiency, final state and adversarial-mutation
  rejection.
- **Sealed-set manifests** with byte counts and SHA-256 per asset, and a
  scenario-partition asset that requires training and sealed-test lineage to
  be disjoint on five fields.
- **Per-run salted canaries** (`cleanroom_eval/free_run.py`,
  `episode_canary`) that are never derivable from the published assets.

## 3. The mapping

| Harbor or recipe file | BankingEnv source | Notes |
|---|---|---|
| `instruction.md` | Task card: title, instructions, actors and allowed actions, tracked objects, surfaces, actions, request contract, deliverable, check list, disclosure barrier, time window | Rendered, not hand-written. Re-checked for oracle leakage after rendering (no expected receipt id, no terminal state triple, no oracle key). A planted canary line is appended on the public dev split only. |
| `task.toml` | Card and sealed-set manifest | `[task]` name `bankingenv/<slug>`, `[metadata]` with episode id, set id, family, work type, split, epoch, sealed and card SHA-256, certificate status and canary visibility; `[verifier]` separate environment; `[agent]` timeout; `[environment]` no network; top-level `artifacts = ["/logs/agent/trajectory.json"]`. Validate against the installed harbor version; field names follow its published schema. [2] |
| `bankingenv.json` (the `archipelago.json` analogue) | Episode and export options | task id, task name, slug, `world_id` (the episode's), `world_short_name` (the family), the family image reference (placeholder until images are built), `required_env_keys` (empty: no external API), `needs_snapshot` false (grading is by replay, not document diff), split, epoch, certificate status. |
| `environment/Dockerfile` | None | Placeholder, as in the recipe. The intended per-family image installs the two packages and, as a follow-up, a tool server exposing the six surfaces inside the sandbox (section 9). |
| `solution/` | Deliberately absent | The scripted path is the oracle. Emitting it would publish the answer next to the prompt; harbor treats the solution as optional. |
| `tests/test.sh` | Written by the exporter | Runs `grade.py`, guarantees a reward file exists. |
| `tests/grade.py` | Written by the exporter; uses the vendored runner | Deterministic trajectory-replay verifier (section 4). |
| `tests/sealed_episode.json` | The sealed episode, byte-identical to the asset (SHA-256 checked against the manifest at export) | The oracle. Lives only under `tests/`, as the recipe's `verifiers.json` and `golden_responses.json` do. |
| `tests/checks.json` | Card `checks` | The deterministic check list, the analogue of `verifiers.json`, but not LLM-judged. |
| `tests/certificate.json` | Written by the exporter | `NOT_ISSUED` with null results until a certification run fills it (section 6). |
| `tests/canary.json` | `episode_canary` over a private salt and the epoch | Present only when a salt was supplied. Carries the canary's visibility (planted in the instruction, or hidden). |
| `tests/Dockerfile` | Written by the exporter | Verifier image for separate mode: Python plus the vendored runner's dependencies. |
| `tests/runner/` | `cleanroom_eval/` and `cleanroom_corpus/` at the exporting commit | Vendored with `--vendor-runner`, pinned by commit in `PINNED.txt`, so grading needs no checkout. |

Rendered text normalises the U+2014 character in sealed titles to a colon;
the sealed bytes under `tests/` are untouched.

## 4. The verifier and the reward

The recipe grades with an LLM judge against hidden rubric criteria and turns
per-criterion scores into the reward. [1] BankingEnv grades
deterministically, and the packaging keeps that: the verifier replays the
agent's trajectory through the sealed episode's observable boundary and
scores what the boundary accepted.

- **Deliverable.** The agent writes `/logs/agent/trajectory.json`: a list of
  steps, each a surface name and a request in the tool-request contract
  (`request_id`, `actor_id`, `action`, `object_versions`, `evidence_refs`),
  in the order they should apply.
- **Replay.** Each request is schema-validated and submitted to the surface
  through `EvaluationSession` in free mode. Unauthorised actors, stale
  versions, ungrounded evidence, unavailable actions and malformed requests
  are rejected without changing state; a resubmitted request id is
  idempotent.
- **Reward.** `reward.txt` carries the preregistered binary: 1 only when
  every tracked object reaches its sealed terminal state and version, no
  state moved outside the contract and no hidden canary was echoed;
  otherwise 0. That is the success rule of
  `cleanroom_eval/assets/preregistration.v1.json` restated for a single
  task. `reward.json` carries the same scalar under `reward`.
- **Diagnostics, never the reward.** `bankingenv-grade.json` records steps,
  accepted and rejected counts, rejection texts, forbidden-key probes,
  canary echoes and state changes outside the contract. A training recipe
  that wants a dense signal can shape from these on its own side; the
  benchmark number stays binary.
- **Self-check.** Before grading, the verifier replays the sealed script
  itself through a fresh session and refuses to grade if that does not
  complete, so a broken vendored runner reads as an error, not as a zero for
  the agent.
- **Residual quality.** Where communication quality matters, this
  repository already limits SME scoring to blinded residual quality with
  deterministic checks taking precedence; that stays outside the reward. [3]

## 5. Worlds, images and the recipe's generator

One image per family (eight worlds), referenced by every task in the family
through `bankingenv.json`, mirrors the recipe's per-world images. The agent
image needs only Python and the two packages; the interactive tool server is
the follow-up in section 9. The recipe reads `archipelago.json` to pick the
image and forward environment keys; `bankingenv.json` carries the same field
names where the meaning matches (`task_id`, `task_name`, `task_slug`,
`world_id`, `world_short_name`, `required_env_keys`, `needs_snapshot`) so a
generator subclass has little to translate. [1]

## 6. Per-task certificates

A task counts only when it carries three certificates, each an executed run
under a frozen protocol with the model, date, trajectory hash and reward
recorded:

1. **Unaided fails.** A frozen reference model given `instruction.md` and no
   environment access does not produce a trajectory that grades 1. This is
   the same instrument-validity check the calibration lane runs as its
   unaided gates (`docs/EVAL-LEDGER.md`, section 1): a task that general
   competence solves measures nothing about the environment.
2. **Naive retrieval fails.** The same model given `instruction.md` plus the
   most lexically similar public evidence records, without interacting with
   the boundary, does not produce a trajectory that grades 1. This is the
   calibration lane's equal-length retrieval control turned into an
   admission condition: the task must require the environment, not a
   lookup.
3. **Oracle passes.** The sealed script replayed through the boundary grades
   1. The verifier executes this as a self-check on every grading run; the
   certificate records it once, under the certification protocol. This is
   the lane's T7 oracle admission gate (a task enters only if demonstrably
   answerable from the source) applied to an environment.

The exporter writes `certificate.json` as `NOT_ISSUED` with every result
null. A certification runner (not in this repository yet) fills it. Tasks
without an issued certificate are excluded from the benchmark split and
flagged in training metadata; they are not silently counted.

## 7. Held-out split policy

- **Public dev split.** The sealed sets in this repository (synthetic,
  already public). Every exported copy carries a planted canary in
  `instruction.md`: `episode_canary` over a private salt, the epoch and the
  episode id. The salt never leaves the exporting machine; the exporter
  writes a registry of canaries per epoch outside the task directories,
  which must be kept private. A model that later reproduces a canary when
  prompted with the task title has seen the published copy.
- **Private test institution.** A second synthetic institution generated by
  the corpus generator with lineage values disjoint from the public one on
  all five partition fields (`scenario_family`, `world_id`,
  `template_family`, `entity_namespace`, `render_seed_family`), enforced by
  `verify_scenario_partitions`. Its tasks are never published and carry a
  hidden canary only (in `tests/canary.json`, never in the instruction), so
  an echo is evidence of a boundary read, as in `free_run.py`. The exporter
  refuses to label anything under the public asset tree as
  `private_test`.
- **Per-epoch re-mint.** Canaries are re-minted per training epoch by the
  exporter (`--epoch`), so a canary memorised in one epoch is dated.
  Re-minting entity identifiers (the `syn_` namespace) per epoch is the
  corpus generator's job through a fresh render seed family and is not done
  by the exporter; it is the natural next step once a generator run is
  wired to the export.
- **Contamination screening.** The existing 13-token hashed-shingle check
  over declared training files stays the gate for any reported transfer
  number; it emits commitments, not source text. [3]

## 8. Using the exporter

```bash
# plan only; writes nothing
python3 scripts/export_harbor.py --dry-run --set v2 --out /tmp/harbor-tasks

# public dev split, epoch 1, canaries planted, runner vendored
python3 scripts/export_harbor.py --set v2 --split public_dev --epoch 1 \
    --salt-file ~/.bankingenv/canary.salt --vendor-runner --out /tmp/harbor-tasks

# private test split from an unpublished world (refused for the public tree)
python3 scripts/export_harbor.py --split private_test --episodes /private/world_x/episodes \
    --salt-file ~/.bankingenv/canary.salt --vendor-runner --out /private/harbor-tasks
```

The exporter fails closed: a sealed asset whose SHA-256 differs from its
manifest entry, a card that drifts from its episode, or a rendered
instruction that names an oracle value stops the export. The parquet
packaging the recipe downloads (`path`, `task_binary`) is a tar-and-gzip of
each directory and is left to the packaging step that owns the dataset repo.
[1]

## 9. Not done yet

1. The in-sandbox tool server that exposes the six surfaces to an agent
   interactively (MCP or HTTP). Until it exists, the agent's deliverable is
   the trajectory file and the verifier replays it, which is harbor's
   trajectory-grading pattern; the environment is still the same contract.
2. The certification runner for section 6 and the frozen protocol it runs
   under.
3. Family images and a registry to push them to.
4. The private test institution itself: a second generator run with disjoint
   lineage.
5. Validation of `task.toml` against the harbor version the recipe pins
   (`harbor[modal]==0.21.0` at the time of the README). [1]

## Footnotes

1. `Mercor-Intelligence/ApexAgents-SkyRL-Recipe`, README as fetched on
   2026-09-03: architecture, data format, `archipelago.json` fields, worlds
   and images, grading, dependency pins. The dev dataset it names carries
   1,928 tasks in its identifier.
2. harbor task-structure documentation (`harborframework.com/docs/tasks`) as
   fetched on 2026-09-03: `task.toml` sections and fields, special paths,
   reward files, separate verifier environments and the trajectory artifact
   pattern.
3. This repository: `README.md`, `cleanroom_eval/README.md`,
   `cleanroom_eval/episode_contract.py`, `cleanroom_eval/contract.py`,
   `cleanroom_eval/free_run.py`, `cleanroom_corpus/eval_adapters.py`,
   `cleanroom_eval/assets/scenario-partitions.v1.json`,
   `cleanroom_eval/assets/preregistration.v1.json`.
