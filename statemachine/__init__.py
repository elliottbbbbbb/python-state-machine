"""
python-statemachine
~~~~~~~~~~~~~~~~~~~

A lightweight, framework-agnostic state machine engine for Python.

Quick start:
    from statemachine import StateMachine, StateResult, StateTransition
    from statemachine import StateMetadata, StateExecutionContext
"""

from statemachine.machine import StateMachine
from statemachine.types import (
    StateExecutionContext,
    StateHistoryEntry,
    StateMetadata,
    StateResult,
    StateTransition,
)
from statemachine.helpers import (
    build_metadata_dict,
    create_state_metadata,
    log_state_execution,
)

__all__ = [
    "StateMachine",
    "StateResult",
    "StateMetadata",
    "StateTransition",
    "StateHistoryEntry",
    "StateExecutionContext",
    "build_metadata_dict",
    "create_state_metadata",
    "log_state_execution",
]
