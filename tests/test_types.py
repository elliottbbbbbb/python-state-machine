"""Tests for statemachine.types."""

import time
from enum import Enum

import pytest

from statemachine.types import (
    StateExecutionContext,
    StateHistoryEntry,
    StateMetadata,
    StateResult,
    StateTransition,
)


class DummyStates(Enum):
    A = "a"
    B = "b"


# ── StateMetadata ──────────────────────────────────────────────────────────────

class TestStateMetadata:
    def test_valid_defaults(self):
        m = StateMetadata(name="Test")
        assert m.max_retries == 3
        assert m.timeout is None
        assert m.failover_state is None

    def test_negative_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries"):
            StateMetadata(name="Bad", max_retries=-1)

    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout"):
            StateMetadata(name="Bad", timeout=0)

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout"):
            StateMetadata(name="Bad", timeout=-5.0)

    def test_positive_timeout_allowed(self):
        m = StateMetadata(name="Ok", timeout=0.001)
        assert m.timeout == 0.001

    def test_zero_retries_allowed(self):
        m = StateMetadata(name="Ok", max_retries=0)
        assert m.max_retries == 0

    def test_failover_state_stored(self):
        m = StateMetadata(name="Ok", failover_state=DummyStates.B)
        assert m.failover_state == DummyStates.B


# ── StateTransition ────────────────────────────────────────────────────────────

class TestStateTransition:
    def test_no_condition_always_allows(self):
        t = StateTransition(DummyStates.A, DummyStates.B)
        assert t.can_transition() is True

    def test_true_condition_allows(self):
        t = StateTransition(DummyStates.A, DummyStates.B, condition=lambda: True)
        assert t.can_transition() is True

    def test_false_condition_blocks(self):
        t = StateTransition(DummyStates.A, DummyStates.B, condition=lambda: False)
        assert t.can_transition() is False

    def test_raising_condition_blocks(self):
        def bad():
            raise RuntimeError("boom")

        t = StateTransition(DummyStates.A, DummyStates.B, condition=bad)
        assert t.can_transition() is False

    def test_condition_called_each_time(self):
        calls = []

        def condition():
            calls.append(1)
            return True

        t = StateTransition(DummyStates.A, DummyStates.B, condition=condition)
        t.can_transition()
        t.can_transition()
        assert len(calls) == 2


# ── StateHistoryEntry ──────────────────────────────────────────────────────────

class TestStateHistoryEntry:
    def test_succeeded_property(self):
        e = StateHistoryEntry(DummyStates.A, StateResult.SUCCESS, duration=0.1)
        assert e.succeeded is True
        assert e.failed is False

    def test_failed_property_on_failure(self):
        e = StateHistoryEntry(DummyStates.A, StateResult.FAILURE, duration=0.1)
        assert e.failed is True
        assert e.succeeded is False

    def test_failed_property_on_timeout(self):
        e = StateHistoryEntry(DummyStates.A, StateResult.TIMEOUT, duration=0.1)
        assert e.failed is True

    def test_to_dict_keys(self):
        e = StateHistoryEntry(DummyStates.A, StateResult.SUCCESS, duration=1.23)
        d = e.to_dict()
        assert d["state"] == "A"
        assert d["result"] == "success"
        assert d["duration"] == 1.23

    def test_to_dict_with_error_message(self):
        e = StateHistoryEntry(
            DummyStates.A, StateResult.FAILURE, duration=0.5, error_message="oops"
        )
        assert e.to_dict()["error_message"] == "oops"


# ── StateExecutionContext ──────────────────────────────────────────────────────

class TestStateExecutionContext:
    def test_elapsed_time_increases(self):
        ctx = StateExecutionContext(current_state=DummyStates.A)
        time.sleep(0.05)
        assert ctx.elapsed_time >= 0.05

    def test_has_timed_out_false_when_none(self):
        ctx = StateExecutionContext(current_state=DummyStates.A)
        assert ctx.has_timed_out(None) is False

    def test_has_timed_out_false_before_threshold(self):
        ctx = StateExecutionContext(current_state=DummyStates.A)
        assert ctx.has_timed_out(9999.0) is False

    def test_has_timed_out_true_after_threshold(self):
        ctx = StateExecutionContext(
            current_state=DummyStates.A,
            start_time=time.time() - 10.0,  # pretend it started 10s ago
        )
        assert ctx.has_timed_out(5.0) is True
