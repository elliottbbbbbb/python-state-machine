"""Tests for statemachine.machine — the core engine."""

import time
from enum import Enum
from typing import Dict, List

import pytest

from statemachine.machine import StateMachine
from statemachine.types import (
    StateExecutionContext,
    StateMetadata,
    StateResult,
    StateTransition,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

class Steps(Enum):
    A = "a"
    B = "b"
    C = "c"
    ERROR = "error"


def _meta(name, **kwargs) -> StateMetadata:
    return StateMetadata(name=name, **kwargs)


def _simple_machine(handlers: Dict[Steps, StateResult], transitions=None) -> StateMachine:
    """
    Build a minimal machine where each state returns a fixed result.

    transitions defaults to A → B → C (linear chain).
    """
    if transitions is None:
        transitions = [
            StateTransition(Steps.A, Steps.B),
            StateTransition(Steps.B, Steps.C),
        ]

    class M(StateMachine):
        def define_states(self): return Steps
        def define_state_metadata(self):
            return {s: _meta(s.name) for s in Steps}
        def define_transitions(self): return transitions
        def get_initial_state(self): return Steps.A

        def _handle_a(self, ctx): return handlers.get(Steps.A, StateResult.SUCCESS)
        def _handle_b(self, ctx): return handlers.get(Steps.B, StateResult.SUCCESS)
        def _handle_c(self, ctx): return handlers.get(Steps.C, StateResult.SUCCESS)
        def _handle_error(self, ctx): return handlers.get(Steps.ERROR, StateResult.SUCCESS)

    return M()


# ── Initialisation ─────────────────────────────────────────────────────────────

class TestInitialisation:
    def test_initialises_on_first_run(self):
        m = _simple_machine({})
        assert not m._initialized
        m.initialize()
        assert m._initialized

    def test_double_initialise_is_safe(self):
        m = _simple_machine({})
        m.initialize()
        m.initialize()  # should not raise
        assert m._initialized

    def test_initial_state_set(self):
        m = _simple_machine({})
        m.initialize()
        assert m.get_current_state() == Steps.A

    def test_missing_metadata_raises(self):
        class Bad(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {}  # empty — missing states
            def define_transitions(self): return []
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx): return StateResult.SUCCESS

        with pytest.raises(ValueError, match="no metadata"):
            Bad().initialize()

    def test_invalid_initial_state_raises(self):
        class Other(Enum):
            X = "x"

        class Bad(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {s: _meta(s.name) for s in Steps}
            def define_transitions(self): return []
            def get_initial_state(self): return Other.X
            def _handle_a(self, ctx): return StateResult.SUCCESS

        with pytest.raises(ValueError, match="Initial state"):
            Bad().initialize()

    def test_transition_with_invalid_from_state_raises(self):
        class Other(Enum):
            X = "x"

        class Bad(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {s: _meta(s.name) for s in Steps}
            def define_transitions(self):
                return [StateTransition(Other.X, Steps.B)]
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx): return StateResult.SUCCESS

        with pytest.raises(ValueError, match="from_state"):
            Bad().initialize()


# ── Happy-path execution ───────────────────────────────────────────────────────

class TestExecution:
    def test_states_execute_in_order(self):
        order = []

        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {s: _meta(s.name) for s in Steps}
            def define_transitions(self):
                return [StateTransition(Steps.A, Steps.B), StateTransition(Steps.B, Steps.C)]
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx): order.append("a"); return StateResult.SUCCESS
            def _handle_b(self, ctx): order.append("b"); return StateResult.SUCCESS
            def _handle_c(self, ctx): order.append("c"); return StateResult.SUCCESS
            def _handle_error(self, ctx): return StateResult.SUCCESS

        M().run()
        assert order == ["a", "b", "c"]

    def test_history_recorded(self):
        m = _simple_machine({})
        m.run()
        history = m.get_history()
        states = [e.state for e in history]
        assert Steps.A in states
        assert Steps.B in states

    def test_history_last_n(self):
        m = _simple_machine({})
        m.run()
        assert len(m.get_history(last_n=1)) == 1

    def test_no_transitions_means_single_state(self):
        m = _simple_machine({}, transitions=[])
        m.run()
        assert m.get_current_state() == Steps.A

    def test_missing_handler_raises_attribute_error(self):
        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {s: _meta(s.name) for s in Steps}
            def define_transitions(self): return []
            def get_initial_state(self): return Steps.A
            # _handle_a deliberately omitted

        with pytest.raises(AttributeError, match="_handle_a"):
            M().run()


# ── Retry logic ────────────────────────────────────────────────────────────────

class TestRetryLogic:
    def test_state_retried_on_failure(self):
        calls = []

        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self):
                return {s: StateMetadata(name=s.name, max_retries=2) for s in Steps}
            def define_transitions(self): return []
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx):
                calls.append(ctx.retry_count)
                # succeed on the third attempt
                return StateResult.SUCCESS if ctx.retry_count >= 2 else StateResult.FAILURE
            def _handle_b(self, ctx): return StateResult.SUCCESS
            def _handle_c(self, ctx): return StateResult.SUCCESS
            def _handle_error(self, ctx): return StateResult.SUCCESS

        M().run()
        assert len(calls) == 3  # attempt 0, retry 1, retry 2

    def test_retry_count_passed_to_handler(self):
        counts = []

        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self):
                return {s: StateMetadata(name=s.name, max_retries=1) for s in Steps}
            def define_transitions(self): return []
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx):
                counts.append(ctx.retry_count)
                return StateResult.FAILURE
            def _handle_b(self, ctx): return StateResult.SUCCESS
            def _handle_c(self, ctx): return StateResult.SUCCESS
            def _handle_error(self, ctx): return StateResult.SUCCESS

        M().run()
        assert counts == [0, 1]

    def test_success_resets_retry_count(self):
        m = _simple_machine({})
        m.run()
        assert m._retry_counts.get(Steps.A, 0) == 0


# ── Failover ───────────────────────────────────────────────────────────────────

class TestFailover:
    def test_failover_state_jumped_to_after_max_retries(self):
        visited = []

        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self):
                return {
                    Steps.A: StateMetadata(name="A", max_retries=0, failover_state=Steps.ERROR),
                    Steps.B: StateMetadata(name="B"),
                    Steps.C: StateMetadata(name="C"),
                    Steps.ERROR: StateMetadata(name="Error"),
                }
            def define_transitions(self):
                return [StateTransition(Steps.A, Steps.B)]
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx): visited.append("a"); return StateResult.FAILURE
            def _handle_b(self, ctx): visited.append("b"); return StateResult.SUCCESS
            def _handle_c(self, ctx): visited.append("c"); return StateResult.SUCCESS
            def _handle_error(self, ctx): visited.append("error"); return StateResult.SUCCESS

        m = M()
        m.run()
        assert "error" in visited
        assert "b" not in visited

    def test_no_failover_just_logs_error(self):
        # Should not raise — just logs and returns FAILURE
        m = _simple_machine({Steps.A: StateResult.FAILURE}, transitions=[])
        m.run()  # no exception expected


# ── Timeout ────────────────────────────────────────────────────────────────────

class TestTimeout:
    def test_state_times_out(self):
        results = []

        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self):
                return {
                    Steps.A: StateMetadata(name="A", max_retries=0, timeout=0.05),
                    Steps.B: StateMetadata(name="B"),
                    Steps.C: StateMetadata(name="C"),
                    Steps.ERROR: StateMetadata(name="Error"),
                }
            def define_transitions(self): return []
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx):
                # Keep returning RETRY so the timeout loop runs
                return StateResult.RETRY
            def _handle_b(self, ctx): return StateResult.SUCCESS
            def _handle_c(self, ctx): return StateResult.SUCCESS
            def _handle_error(self, ctx): return StateResult.SUCCESS

        m = M()
        m.run()
        history = m.get_history()
        # The final recorded result for A should be TIMEOUT
        a_entries = [e for e in history if e.state == Steps.A]
        assert any(e.result.value == "timeout" for e in a_entries)


# ── Watchdog ───────────────────────────────────────────────────────────────────

class TestWatchdog:
    def test_watchdog_raises_when_idle_too_long(self):
        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {s: _meta(s.name) for s in Steps}
            def define_transitions(self): return []
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx): return StateResult.SUCCESS
            def _handle_b(self, ctx): return StateResult.SUCCESS
            def _handle_c(self, ctx): return StateResult.SUCCESS
            def _handle_error(self, ctx): return StateResult.SUCCESS

        m = M()
        m.enable_watchdog(timeout_seconds=0.001)
        # Backdate last activity so the watchdog fires immediately
        m._watchdog_last_activity = time.time() - 10.0

        with pytest.raises(RuntimeError, match="Watchdog"):
            m.run()

    def test_record_activity_resets_watchdog(self):
        m = _simple_machine({})
        m.enable_watchdog(timeout_seconds=60.0)
        m._watchdog_last_activity = time.time() - 10.0
        m.record_activity()
        # Should not raise
        m._check_watchdog()

    def test_watchdog_disabled_by_default(self):
        m = _simple_machine({})
        m._watchdog_last_activity = time.time() - 99999
        m._check_watchdog()  # should not raise


# ── Conditional transitions ────────────────────────────────────────────────────

class TestConditionalTransitions:
    def test_condition_false_skips_transition(self):
        visited = []

        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {s: _meta(s.name) for s in Steps}
            def define_transitions(self):
                return [StateTransition(Steps.A, Steps.B, condition=lambda: False)]
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx): visited.append("a"); return StateResult.SUCCESS
            def _handle_b(self, ctx): visited.append("b"); return StateResult.SUCCESS
            def _handle_c(self, ctx): return StateResult.SUCCESS
            def _handle_error(self, ctx): return StateResult.SUCCESS

        M().run()
        assert "b" not in visited

    def test_condition_true_allows_transition(self):
        visited = []

        class M(StateMachine):
            def define_states(self): return Steps
            def define_state_metadata(self): return {s: _meta(s.name) for s in Steps}
            def define_transitions(self):
                return [StateTransition(Steps.A, Steps.B, condition=lambda: True)]
            def get_initial_state(self): return Steps.A
            def _handle_a(self, ctx): visited.append("a"); return StateResult.SUCCESS
            def _handle_b(self, ctx): visited.append("b"); return StateResult.SUCCESS
            def _handle_c(self, ctx): return StateResult.SUCCESS
            def _handle_error(self, ctx): return StateResult.SUCCESS

        M().run()
        assert "b" in visited


# ── Reset ──────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_returns_to_initial_state(self):
        m = _simple_machine({})
        m.run()
        m.reset()
        assert m.get_current_state() == Steps.A

    def test_reset_clears_retry_counts(self):
        m = _simple_machine({Steps.A: StateResult.FAILURE})
        m.initialize()
        m._retry_counts[Steps.A] = 3
        m.reset()
        assert m._retry_counts == {}
