"""
State machine data types and structures.

Defines the core types used by the state machine framework:
- StateResult: Outcomes of state execution
- StateMetadata: Configuration for individual states
- StateTransition: Defines allowed state transitions
- StateHistoryEntry: Tracks state execution history
- StateExecutionContext: Runtime context passed to state handlers
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class StateResult(Enum):
    """
    Result of executing a state.

    Determines the next action the state machine should take.
    """

    SUCCESS = "success"   # State completed successfully, proceed to next state
    FAILURE = "failure"   # State failed, may retry or transition to failover
    RETRY = "retry"       # State should be retried immediately
    SKIP = "skip"         # State skipped (condition not met), proceed to next
    TIMEOUT = "timeout"   # State timed out, transition to failover


@dataclass
class StateMetadata:
    """
    Metadata and configuration for a single state.

    Defines retry behaviour, timeouts, and failover logic for a state.

    Args:
        name: Display name for the state.
        description: Brief description of what the state does.
        max_retries: Maximum retry attempts before failover (default: 3).
        timeout: Max execution time in seconds. None means no timeout.
        failover_state: State to transition to after max retries are exhausted.

    Raises:
        ValueError: If max_retries < 0 or timeout <= 0.
    """

    name: str
    description: str = ""
    max_retries: int = 3
    timeout: Optional[float] = None
    failover_state: Optional[Enum] = None

    def __post_init__(self):
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError(f"timeout must be > 0 or None, got {self.timeout}")


@dataclass
class StateTransition:
    """
    Defines a transition between two states.

    Args:
        from_state: The state this transition originates from.
        to_state: The state this transition leads to.
        condition: Optional callable. If provided, must return True for the
                   transition to occur. Exceptions in the condition are caught
                   and treated as False.
    """

    from_state: Enum
    to_state: Enum
    condition: Optional[Callable[[], bool]] = None

    def can_transition(self) -> bool:
        """
        Check if this transition is currently allowed.

        Returns:
            True if no condition is set, or the condition returns True.
            False if the condition returns False or raises an exception.
        """
        if self.condition is None:
            return True
        try:
            return bool(self.condition())
        except Exception:
            return False


@dataclass
class StateHistoryEntry:
    """
    Records the execution of a single state.

    Tracks timing, result, and retry information for debugging and analysis.
    """

    state: Enum
    result: StateResult
    duration: float
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    error_message: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        """True if the state completed successfully."""
        return self.result == StateResult.SUCCESS

    @property
    def failed(self) -> bool:
        """True if the state failed or timed out."""
        return self.result in (StateResult.FAILURE, StateResult.TIMEOUT)

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "state": self.state.name if isinstance(self.state, Enum) else str(self.state),
            "result": self.result.value,
            "duration": self.duration,
            "timestamp": self.timestamp,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


@dataclass
class StateExecutionContext:
    """
    Runtime context passed to every state handler.

    Provides timing information and retry count so handlers can make
    decisions based on how long they have been running.

    Args:
        current_state: The state currently being executed.
        retry_count: How many times this state has been retried so far.
        start_time: Epoch time when execution began (defaults to now).
        metadata: Arbitrary key/value pairs for handler-specific data.
    """

    current_state: Enum
    retry_count: int = 0
    start_time: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    @property
    def elapsed_time(self) -> float:
        """Seconds elapsed since this state started executing."""
        return time.time() - self.start_time

    def has_timed_out(self, timeout: Optional[float]) -> bool:
        """
        Check whether the state has exceeded a timeout.

        Args:
            timeout: Seconds allowed. None means never time out.

        Returns:
            True if elapsed_time >= timeout, False otherwise.
        """
        if timeout is None:
            return False
        return self.elapsed_time >= timeout
