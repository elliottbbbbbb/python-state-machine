"""
StateMachine — a reusable, framework-agnostic state machine engine.

Features:
- Declarative state, metadata, and transition definitions via abstract methods
- Automatic retry logic with configurable per-state retry limits
- Per-state timeouts with automatic failover on expiry
- Watchdog that stops execution if no progress is recorded within a threshold
- Bounded execution history (deque) for debugging and introspection
- Convention-based state handler dispatch (_handle_<state_value>)

Usage:
    from enum import Enum
    from statemachine.machine import StateMachine
    from statemachine.types import StateResult, StateMetadata, StateTransition, StateExecutionContext
    from statemachine.helpers import build_metadata_dict

    class Steps(Enum):
        FETCH = "fetch"
        PROCESS = "process"
        SAVE = "save"

    class MyMachine(StateMachine):
        def define_states(self): return Steps
        def define_state_metadata(self):
            return build_metadata_dict(Steps, {
                Steps.FETCH:   {"name": "Fetch",   "timeout": 10.0, "failover": Steps.SAVE},
                Steps.PROCESS: {"name": "Process", "max_retries": 2},
                Steps.SAVE:    {"name": "Save"},
            })
        def define_transitions(self):
            return [
                StateTransition(Steps.FETCH, Steps.PROCESS),
                StateTransition(Steps.PROCESS, Steps.SAVE),
            ]
        def get_initial_state(self): return Steps.FETCH

        def _handle_fetch(self, ctx): ...
        def _handle_process(self, ctx): ...
        def _handle_save(self, ctx): ...
"""

import logging
import time
from abc import ABC, abstractmethod
from collections import deque
from enum import Enum
from typing import Callable, Dict, List, Optional

from statemachine.types import (
    StateExecutionContext,
    StateHistoryEntry,
    StateMetadata,
    StateResult,
    StateTransition,
)

logger = logging.getLogger(__name__)


class StateMachine(ABC):
    """
    Base class for all state machines.

    Subclass this and implement the four abstract methods plus one
    ``_handle_<state_value>`` method per state.

    Attributes:
        MAX_STATES_PER_RUN: Safety cap on state transitions per ``run()``
                            call to prevent infinite loops (default: 100).
    """

    MAX_STATES_PER_RUN: int = 100

    def __init__(self):
        self._states: Optional[type[Enum]] = None
        self._state_metadata: Dict[Enum, StateMetadata] = {}
        self._transitions: List[StateTransition] = []
        self._current_state: Optional[Enum] = None
        self._transition_map: Dict[Enum, List[StateTransition]] = {}

        self._state_history: deque = deque(maxlen=100)
        self._retry_counts: Dict[Enum, int] = {}

        self._initialized: bool = False

        # Watchdog (disabled by default)
        self._watchdog_timeout: Optional[float] = None
        self._watchdog_last_activity: float = time.time()
        self._watchdog_warned: bool = False

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def define_states(self) -> type[Enum]:
        """Return the Enum class that defines all valid states."""

    @abstractmethod
    def define_state_metadata(self) -> Dict[Enum, StateMetadata]:
        """Return a mapping of every state to its StateMetadata."""

    @abstractmethod
    def define_transitions(self) -> List[StateTransition]:
        """Return the list of allowed StateTransitions."""

    @abstractmethod
    def get_initial_state(self) -> Enum:
        """Return the state the machine should start in."""

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """
        Initialise the state machine.

        Called automatically by ``run()`` if not already done.
        Validates that every state has metadata and all transitions
        reference valid states.

        Raises:
            ValueError: On invalid configuration.
        """
        if self._initialized:
            return

        self._states = self.define_states()
        self._state_metadata = self.define_state_metadata()
        self._transitions = self.define_transitions()
        self._current_state = self.get_initial_state()

        # Build O(1) lookup map
        self._transition_map = {}
        for t in self._transitions:
            self._transition_map.setdefault(t.from_state, []).append(t)

        self._validate()
        self._initialized = True

        logger.info(
            f"{self.__class__.__name__} initialised — "
            f"{len(self._state_metadata)} states, "
            f"{len(self._transitions)} transitions, "
            f"starting at {self._current_state.name}"
        )

    def _validate(self) -> None:
        """Validate configuration. Raises ValueError on problems."""
        for state in self._states:
            if state not in self._state_metadata:
                raise ValueError(f"State {state} has no metadata defined")

        if self._current_state not in self._states:
            raise ValueError(
                f"Initial state {self._current_state} not found in states enum"
            )

        for t in self._transitions:
            if t.from_state not in self._states:
                raise ValueError(f"Transition from_state {t.from_state} not in states enum")
            if t.to_state not in self._states:
                raise ValueError(f"Transition to_state {t.to_state} not in states enum")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Run the state machine to completion.

        Executes states in sequence, following transitions, until no
        valid transition exists or MAX_STATES_PER_RUN is reached.
        Resets retry counts at the start of each run.
        """
        if not self._initialized:
            self.initialize()

        self._retry_counts.clear()
        steps = 0

        while steps < self.MAX_STATES_PER_RUN:
            self._check_watchdog()

            prev_state = self._current_state
            result = self._execute_state(self._current_state)

            # If _execute_state changed _current_state (failover), skip the
            # normal transition lookup and let the loop execute the new state.
            if self._current_state != prev_state:
                steps += 1
                continue

            next_state = self._get_next_state(self._current_state, result)
            if next_state is None:
                logger.info(f"No further transitions from {self._current_state.name} — run complete")
                break

            logger.info(f"Transition: {self._current_state.name} → {next_state.name}")
            self._current_state = next_state
            steps += 1

        if steps >= self.MAX_STATES_PER_RUN:
            logger.error(f"Safety limit reached ({self.MAX_STATES_PER_RUN} states) — stopping")

    # ------------------------------------------------------------------
    # State execution
    # ------------------------------------------------------------------

    def _execute_state(self, state: Enum) -> StateResult:
        """
        Execute a single state with retry and timeout handling.

        On FAILURE / RETRY / TIMEOUT:
          - If retries remain, recurse and retry.
          - If retries exhausted and a failover_state is configured,
            jump directly to it and return FAILURE.
          - Otherwise log the error and return FAILURE.

        On SUCCESS, reset the retry counter for this state.
        """
        metadata = self._state_metadata[state]
        retry_count = self._retry_counts.get(state, 0)

        logger.info(
            f"Executing {state.name} "
            f"(attempt {retry_count + 1}/{metadata.max_retries + 1})"
        )

        context = StateExecutionContext(current_state=state, retry_count=retry_count)
        start = time.time()
        result = StateResult.FAILURE
        error_message = None

        # Resolve handler before entering the try block so that a missing
        # handler raises immediately (programming error, not a runtime failure).
        handler = self._get_state_handler(state)

        try:
            while not context.has_timed_out(metadata.timeout):
                result = handler(context)
                if result != StateResult.RETRY:
                    break
                time.sleep(0.1)

            if context.has_timed_out(metadata.timeout):
                logger.warning(f"{state.name} timed out after {metadata.timeout}s")
                result = StateResult.TIMEOUT
                error_message = f"Timeout after {metadata.timeout}s"

        except Exception as e:
            logger.error(f"Error in {state.name}: {e}", exc_info=True)
            result = StateResult.FAILURE
            error_message = str(e)

        duration = time.time() - start

        self._state_history.append(
            StateHistoryEntry(
                state=state,
                result=result,
                duration=duration,
                retry_count=retry_count,
                error_message=error_message,
            )
        )

        logger.info(f"{state.name} → {result.value} ({duration:.2f}s)")

        # Retry / failover logic
        if result in (StateResult.FAILURE, StateResult.RETRY, StateResult.TIMEOUT):
            if retry_count < metadata.max_retries:
                self._retry_counts[state] = retry_count + 1
                return self._execute_state(state)
            else:
                if metadata.failover_state:
                    logger.warning(
                        f"{state.name} failed after {metadata.max_retries + 1} attempts — "
                        f"failing over to {metadata.failover_state.name}"
                    )
                    self._current_state = metadata.failover_state
                    self._retry_counts[state] = 0
                else:
                    logger.error(f"{state.name} failed with no failover defined")

        if result == StateResult.SUCCESS:
            self._retry_counts[state] = 0

        return result

    def _get_state_handler(
        self, state: Enum
    ) -> Callable[[StateExecutionContext], StateResult]:
        """
        Resolve the handler method for a state by convention.

        Looks for a method named ``_handle_<state.value.lower()>`` on self.

        Raises:
            AttributeError: If no matching method is found.
        """
        name = f"_handle_{state.value.lower()}"
        handler = getattr(self, name, None)
        if handler is None:
            raise AttributeError(
                f"No handler '{name}' found on {self.__class__.__name__}. "
                f"Implement this method to handle the '{state.name}' state."
            )
        return handler

    def _get_next_state(self, current_state: Enum, result: StateResult) -> Optional[Enum]:
        """
        Determine the next state based on declared transitions.

        Returns the first transition from current_state whose condition
        passes, or None if no valid transition exists.
        """
        for transition in self._transition_map.get(current_state, []):
            if transition.can_transition():
                return transition.to_state
        return None

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def enable_watchdog(self, timeout_seconds: float = 300.0) -> None:
        """
        Enable the idle watchdog.

        If ``record_activity()`` is not called within ``timeout_seconds``,
        ``run()`` will raise a RuntimeError.

        Args:
            timeout_seconds: Idle threshold in seconds (default: 300).
        """
        self._watchdog_timeout = timeout_seconds
        self._watchdog_last_activity = time.time()
        self._watchdog_warned = False
        logger.info(f"Watchdog enabled: {timeout_seconds:.0f}s idle threshold")

    def record_activity(self) -> None:
        """Reset the watchdog timer. Call this when meaningful progress is made."""
        self._watchdog_last_activity = time.time()
        self._watchdog_warned = False

    def _check_watchdog(self) -> None:
        """Raise RuntimeError if the watchdog threshold has been exceeded."""
        if self._watchdog_timeout is None:
            return

        idle = time.time() - self._watchdog_last_activity

        if idle >= self._watchdog_timeout:
            raise RuntimeError(
                f"Watchdog: no activity for {idle:.0f}s "
                f"(threshold: {self._watchdog_timeout:.0f}s)"
            )

        warn_at = self._watchdog_timeout * 0.8
        if idle >= warn_at and not self._watchdog_warned:
            remaining = self._watchdog_timeout - idle
            logger.warning(
                f"Watchdog: idle {idle:.0f}s — will stop in {remaining:.0f}s"
            )
            self._watchdog_warned = True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_current_state(self) -> Optional[Enum]:
        """Return the current state."""
        return self._current_state

    def get_history(self, last_n: Optional[int] = None) -> List[StateHistoryEntry]:
        """
        Return execution history.

        Args:
            last_n: If provided, return only the last N entries.
        """
        history = list(self._state_history)
        return history[-last_n:] if last_n is not None else history

    def reset(self) -> None:
        """Reset the machine to its initial state and clear retry counts."""
        self._current_state = self.get_initial_state()
        self._retry_counts.clear()
        logger.info(f"Reset to {self._current_state.name}")
