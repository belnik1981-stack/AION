"""Safe adaptive learning layer for AION.

This layer learns reliability of models/sources and can roll back its own state.
It does not modify base-model weights and never modifies Truth.
"""

from .controller import (
    AdaptiveLearningController,
    LearningPolicy,
    LearningStateError,
)

__all__ = ["AdaptiveLearningController", "LearningPolicy", "LearningStateError"]
