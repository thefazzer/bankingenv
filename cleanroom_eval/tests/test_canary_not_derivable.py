"""The hidden canary must not be computable from published assets alone."""
import re

from cleanroom_eval.contract import digest
from cleanroom_eval.free_run import episode_canary
from cleanroom_eval.runner import ArmRunner


def test_runner_source_has_no_unsalted_canary_derivation():
    import inspect

    import cleanroom_eval.runner as runner_module
    source = inspect.getsource(runner_module)
    assert not re.search(r"CANARY-\{digest\(", source), (
        "runner derives the canary from public episode ids - "
        "an agent holding the published tree can echo it")


def test_two_runs_disagree_on_the_same_episode_canary():
    a = ArmRunner.__new__(ArmRunner)
    b = ArmRunner.__new__(ArmRunner)
    import secrets

    a.run_salt = secrets.token_hex(16)
    b.run_salt = secrets.token_hex(16)
    episode_id = "episode_settlement_exceptions_alpha_01"
    ca = episode_canary(a.run_salt, episode_id)
    cb = episode_canary(b.run_salt, episode_id)
    assert ca != cb
    assert ca != "CANARY-" + digest({"episode_id": episode_id})[:16]
