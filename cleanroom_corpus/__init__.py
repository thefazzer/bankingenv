"""Deterministic clean-room corpus generation and curated synthetic storage."""

from .generator import (
    GeneratorConfig,
    SyntheticCorpusGenerator,
    institution_scale_config,
    materialize_state,
)
from .model import SyntheticInstitution, SyntheticPerson
from .registry import StoreRegistry

__all__ = [
    "GeneratorConfig",
    "StoreRegistry",
    "SyntheticCorpusGenerator",
    "SyntheticInstitution",
    "SyntheticPerson",
    "institution_scale_config",
    "materialize_state",
]
