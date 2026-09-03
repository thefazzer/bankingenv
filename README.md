<title>BankingEnv</title>

# BankingEnv

A fully synthetic banking-operations world and a hash-sealed evaluation
contract for long-horizon agent work in capital-markets operations —
settlement, booking and allocations, reconciliation, collateral and margin,
permissions and release, temporal causality and evidence sufficiency.

Everything here is invented. The institution (Ficta Meridian Bank), its
people, systems, episodes, identifiers and documents are generated from
seeded synthetic pipelines and marked `CLEANROOM_SYNTHETIC`. No real firm's
confidential data or work product appears in this repository; public-source
citations are attributed where used.

Legal work recently got this treatment: Harvey's open-source
[LAB](https://github.com/harveyai/harvey-labs) benchmark and the
Calderwood & Harkness synthetic law firm (built with EngramLab) showed that
domains with confidential work product and expensive, sparse reward need a
clean, cheap verification signal before agents can improve against them.
Banking operations has the same structure. BankingEnv is that sibling.

## What is in the box

- **`cleanroom_eval/`** — the evaluation contract: forty hash-sealed
  long-horizon episodes across eight operational families; a frozen
  competency taxonomy and six tool-surface contracts; preregistered
  experiment designs (BASE / SFT / RL with matched controls); byte-exact
  sealed-set manifests. The episode replayer deterministically checks
  chronology, referential integrity, authorization, monotonic object
  versions, idempotency, per-currency ledger conservation, evidence
  sufficiency and adversarial-mutation rejection — a failed check blocks
  success. Anti-cheat canaries are minted per run and are never derivable
  from the published assets.
- **`cleanroom_corpus/`** — the synthetic institution generator: the world
  model, registries, cast identity pipelines and eval adapters that produce
  Ficta Meridian Bank and export episodes conforming to the eval schemas.

## Quickstart

```bash
pip install -r requirements.txt
python3 -m pytest cleanroom_eval/tests -q         # contract self-checks
python3 -m cleanroom_eval.benchmark --help        # sealed-episode benchmark runner
```

Model access is provider-agnostic; see `cleanroom_eval/real_provider.py` for
the provider surface.

## Design commitments

1. **Verifier-first.** The sealed episodes and preregistrations are the
   product; scores are downstream of a frozen, auditable contract.
2. **No unearned claims.** Preregistration files lock metrics, denominators
   and missing-result policy before execution; matched controls ship with
   every training arm.
3. **What the seals prove.** Sealed hashes prove immutability: the episodes
   and manifests you clone are byte-identical to the ones any reported run
   used. Graded evaluation results under preregistration are available, with
   their scoring material, to counterparties under NDA.

## Ledger and packaging

- [docs/EVAL-LEDGER.md](docs/EVAL-LEDGER.md): what the preregistered
  calibration lane behind BankingEnv has and has not established as of
  2026-09-03, in the lane's own status vocabulary. It reports no graded
  figure for the forty sealed episodes.
- [docs/HARBOR-PACKAGING.md](docs/HARBOR-PACKAGING.md): how a sealed
  episode maps to a harbor task directory (instruction, config, verifier) of
  the kind Mercor's ApexAgents-SkyRL recipe consumes, with the split policy
  and per-task certificates. `scripts/export_harbor.py` writes that layout
  from the sealed assets and has a dry-run mode.

## License

MIT — see [LICENSE](LICENSE).
