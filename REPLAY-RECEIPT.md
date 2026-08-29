# Clean-machine replay receipt

- **Environment:** pristine `python:3.12-slim` Docker container; this
  repository's file tree only; dependencies from `requirements.txt`; no access
  to any private repository, corpus, or credential. Exit codes checked
  unmasked for every stage.
- **Results:**
  - Contract self-checks: **43/43 passed** (`python -m pytest cleanroom_eval/tests`)
  - Sealed-set integrity: **44/44** assets verified against
    `sealed-set.manifest.v1.json`; **82/82** against
    `sealed-set.manifest.v2.json` (sha256 + byte length, zero mismatches)
  - Benchmark runner: `python -m cleanroom_eval.benchmark --help` imports and
    runs clean
  - Anti-cheat canaries: regression test confirms they are not derivable from
    the published assets
- **Meaning:** the published artifact is self-contained and its evaluation
  contract reproduces from a fresh machine with nothing but this tree.
  Model-graded scores are a separate, provider-dependent exercise governed by
  the preregistration files in `cleanroom_eval/assets/`.
