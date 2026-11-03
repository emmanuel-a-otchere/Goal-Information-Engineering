"""goal-model: machine-native goal models.

A reference implementation of the GOAL metamodel (see docs/GOAL-METAMODEL.md).
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "0.2.0"

from .model import GoalModel, load  # noqa: F401
from .rules import check_model, find_issues  # noqa: F401
