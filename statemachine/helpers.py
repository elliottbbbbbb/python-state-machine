"""
Helper utilities for building state machines.

Provides convenience functions and decorators that reduce boilerplate
when defining states, metadata, and transitions.
"""

import logging
from enum import Enum
from functools import wraps
from typing import Dict, Optional

from statemachine.types import StateExecutionContext, StateMetadata, StateResult

logger = logging.getLogger(__name__)


def create_state_metadata(
    name: str,
    description: str = "",
    max_retries: int = 3,
    timeout: Optional[float] = None,
    failover_state: Optional[Enum] = None,
) -> StateMetadata:
    """
    Create a StateMetadata instance with sensible defaults.

    Args:
        name: Display name for the state.
        description: Brief description of what the state does.
        max_retries: Maximum retry attempts before failover (default: 3).
        timeout: Maximum execution time in seconds (default: None = no limit).
        failover_state: State to transition to after exhausting retries.

    Returns:
        A configured StateMetadata instance.

    Example:
        metadata = create_state_metadata(
            name="Fetch",
            description="Fetch data from API",
            timeout=30.0,
            failover_state=MyStates.ERROR,
        )
    """
    return StateMetadata(
        name=name,
        description=description,
        max_retries=max_retries,
        timeout=timeout,
        failover_state=failover_state,
    )


def build_metadata_dict(
    states_enum: type[Enum],
    configs: Dict[Enum, dict],
) -> Dict[Enum, StateMetadata]:
    """
    Build a state metadata dictionary from a compact configuration.

    Reduces boilerplate when defining metadata for many states at once.
    Each state maps to a plain dict instead of a verbose StateMetadata() call.

    Args:
        states_enum: The states Enum class (used for documentation clarity).
        configs: Mapping of state → config dict. Supported keys:
            - ``name`` (str, required): Display name.
            - ``description`` (str, optional): Brief description.
            - ``max_retries`` (int, optional, default 3): Retry limit.
            - ``timeout`` (float, optional): Timeout in seconds.
            - ``failover`` (Enum, optional): Failover state.

    Returns:
        Dict mapping each state to a StateMetadata instance.

    Raises:
        ValueError: If any config dict is missing the required ``name`` key.

    Example:
        metadata = build_metadata_dict(MyStates, {
            MyStates.IDLE: {"name": "Idle", "max_retries": 1},
            MyStates.WORK: {"name": "Work", "timeout": 60.0, "failover": MyStates.IDLE},
        })
    """
    result = {}
    for state, config in configs.items():
        if "name" not in config:
            raise ValueError(f"State {state} config missing required 'name' field")
        result[state] = create_state_metadata(
            name=config["name"],
            description=config.get("description", ""),
            max_retries=config.get("max_retries", 3),
            timeout=config.get("timeout", None),
            failover_state=config.get("failover", None),
        )
    return result


def log_state_execution(func):
    """
    Decorator that adds automatic entry/exit logging to state handlers.

    Logs the state name and result at DEBUG level without requiring manual
    logger calls inside every handler.

    Usage:
        @log_state_execution
        def _handle_work(self, context: StateExecutionContext) -> StateResult:
            # No manual logging needed for entry/exit
            return StateResult.SUCCESS

    Note:
        Optional — use selectively where the automatic logging is sufficient.
        Handlers that need more detailed context can log manually instead.
    """

    @wraps(func)
    def wrapper(self, context: StateExecutionContext) -> StateResult:
        state_name = context.current_state.name.upper()
        logger.debug(f"{state_name}: Starting...")
        result = func(self, context)
        if result == StateResult.SUCCESS:
            logger.debug(f"{state_name}: Complete")
        elif result == StateResult.FAILURE:
            logger.debug(f"{state_name}: Failed")
        elif result == StateResult.RETRY:
            logger.debug(f"{state_name}: Retrying...")
        return result

    return wrapper
