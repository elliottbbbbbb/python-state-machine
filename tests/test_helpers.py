"""Tests for statemachine.helpers."""

from enum import Enum

import pytest

from statemachine.helpers import build_metadata_dict, create_state_metadata, log_state_execution
from statemachine.types import StateExecutionContext, StateMetadata, StateResult


class Steps(Enum):
    A = "a"
    B = "b"
    C = "c"


# ── create_state_metadata ──────────────────────────────────────────────────────

class TestCreateStateMetadata:
    def test_returns_state_metadata(self):
        m = create_state_metadata("Step A")
        assert isinstance(m, StateMetadata)

    def test_name_stored(self):
        m = create_state_metadata("My State")
        assert m.name == "My State"

    def test_defaults(self):
        m = create_state_metadata("X")
        assert m.max_retries == 3
        assert m.timeout is None
        assert m.failover_state is None
        assert m.description == ""

    def test_custom_values(self):
        m = create_state_metadata(
            "X",
            description="does stuff",
            max_retries=1,
            timeout=5.0,
            failover_state=Steps.C,
        )
        assert m.description == "does stuff"
        assert m.max_retries == 1
        assert m.timeout == 5.0
        assert m.failover_state == Steps.C


# ── build_metadata_dict ────────────────────────────────────────────────────────

class TestBuildMetadataDict:
    def test_returns_dict_with_all_states(self):
        result = build_metadata_dict(Steps, {
            Steps.A: {"name": "A"},
            Steps.B: {"name": "B"},
        })
        assert Steps.A in result
        assert Steps.B in result

    def test_values_are_state_metadata(self):
        result = build_metadata_dict(Steps, {Steps.A: {"name": "A"}})
        assert isinstance(result[Steps.A], StateMetadata)

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            build_metadata_dict(Steps, {Steps.A: {"max_retries": 1}})

    def test_optional_fields_applied(self):
        result = build_metadata_dict(Steps, {
            Steps.A: {
                "name": "A",
                "description": "desc",
                "max_retries": 0,
                "timeout": 10.0,
                "failover": Steps.B,
            }
        })
        m = result[Steps.A]
        assert m.description == "desc"
        assert m.max_retries == 0
        assert m.timeout == 10.0
        assert m.failover_state == Steps.B

    def test_empty_configs_returns_empty_dict(self):
        result = build_metadata_dict(Steps, {})
        assert result == {}


# ── log_state_execution ────────────────────────────────────────────────────────

class TestLogStateExecution:
    """Verifies the decorator passes through return values correctly."""

    def _make_handler(self, return_value: StateResult):
        class FakeBot:
            @log_state_execution
            def _handle_a(self, ctx: StateExecutionContext) -> StateResult:
                return return_value

        return FakeBot()

    def _ctx(self):
        return StateExecutionContext(current_state=Steps.A)

    def test_success_passthrough(self):
        bot = self._make_handler(StateResult.SUCCESS)
        assert bot._handle_a(self._ctx()) == StateResult.SUCCESS

    def test_failure_passthrough(self):
        bot = self._make_handler(StateResult.FAILURE)
        assert bot._handle_a(self._ctx()) == StateResult.FAILURE

    def test_retry_passthrough(self):
        bot = self._make_handler(StateResult.RETRY)
        assert bot._handle_a(self._ctx()) == StateResult.RETRY

    def test_preserves_function_name(self):
        class FakeBot:
            @log_state_execution
            def _handle_a(self, ctx):
                return StateResult.SUCCESS

        assert FakeBot._handle_a.__name__ == "_handle_a"
