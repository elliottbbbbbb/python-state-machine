# python-statemachine

A lightweight, framework-agnostic state machine engine for Python 3.10+.

Define states as an `Enum`, declare metadata and transitions, implement one method per state. The engine handles retries, timeouts, failover, and execution history automatically.

## Features

- **Declarative** — states, transitions, and metadata defined via four abstract methods
- **Retry logic** — configurable per-state retry limit with automatic re-execution
- **Timeouts** — per-state execution time limits with automatic failover on expiry
- **Failover** — define a fallback state for when retries are exhausted
- **Watchdog** — stops execution if no progress is recorded within a threshold
- **History** — bounded execution log for debugging and introspection
- **Convention-based dispatch** — handlers resolved automatically from state names

## Installation

```bash
pip install -e .
```

## Quick start

```python
from enum import Enum
from statemachine import StateMachine, StateResult, StateTransition, StateExecutionContext
from statemachine import build_metadata_dict

class OrderSteps(Enum):
    VALIDATE = "validate"
    CHARGE   = "charge"
    SHIP     = "ship"
    ERROR    = "error"

class OrderMachine(StateMachine):

    def define_states(self):
        return OrderSteps

    def define_state_metadata(self):
        return build_metadata_dict(OrderSteps, {
            OrderSteps.VALIDATE: {"name": "Validate", "max_retries": 1},
            OrderSteps.CHARGE:   {"name": "Charge",   "timeout": 30.0, "failover": OrderSteps.ERROR},
            OrderSteps.SHIP:     {"name": "Ship"},
            OrderSteps.ERROR:    {"name": "Error",    "max_retries": 0},
        })

    def define_transitions(self):
        return [
            StateTransition(OrderSteps.VALIDATE, OrderSteps.CHARGE),
            StateTransition(OrderSteps.CHARGE,   OrderSteps.SHIP),
        ]

    def get_initial_state(self):
        return OrderSteps.VALIDATE

    def _handle_validate(self, ctx: StateExecutionContext) -> StateResult:
        print("Validating order...")
        return StateResult.SUCCESS

    def _handle_charge(self, ctx: StateExecutionContext) -> StateResult:
        print("Charging customer...")
        return StateResult.SUCCESS

    def _handle_ship(self, ctx: StateExecutionContext) -> StateResult:
        print("Shipping order!")
        return StateResult.SUCCESS

    def _handle_error(self, ctx: StateExecutionContext) -> StateResult:
        print("Handling error...")
        return StateResult.SUCCESS


machine = OrderMachine()
machine.run()
```

## State results

| Result | Meaning |
|---|---|
| `SUCCESS` | State completed — follow transitions to next state |
| `FAILURE` | State failed — retry if retries remain, otherwise failover |
| `RETRY` | Retry immediately without counting as a failed attempt |
| `SKIP` | Skip this state — follow transitions as if succeeded |
| `TIMEOUT` | State exceeded its time limit — treated as failure |

## Metadata options

```python
from statemachine import StateMetadata

StateMetadata(
    name="My State",          # Display name (required)
    description="Does stuff", # Optional description
    max_retries=3,            # Retry attempts before failover (default: 3)
    timeout=30.0,             # Max seconds before timeout (default: None)
    failover_state=MyStates.ERROR,  # State to jump to after exhausting retries
)
```

Or use the compact helper:

```python
from statemachine import build_metadata_dict

metadata = build_metadata_dict(MyStates, {
    MyStates.WORK: {
        "name": "Work",
        "timeout": 60.0,
        "failover": MyStates.ERROR,
    },
})
```

## Conditional transitions

```python
from statemachine import StateTransition

StateTransition(
    from_state=MyStates.CHECK,
    to_state=MyStates.PROCEED,
    condition=lambda: some_flag is True,  # Only transition if this returns True
)
```

## Watchdog

Stop execution automatically if no progress is made:

```python
machine = MyMachine()
machine.enable_watchdog(timeout_seconds=120)

# In a state handler, call this when meaningful work is done:
def _handle_work(self, ctx):
    do_something()
    self.record_activity()  # resets the watchdog timer
    return StateResult.SUCCESS
```

## Introspection

```python
machine.get_current_state()        # Current state enum value
machine.get_history()              # All StateHistoryEntry records
machine.get_history(last_n=5)      # Last 5 entries
machine.reset()                    # Return to initial state
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

## Architecture notes

State handlers are resolved by convention: a state with value `"charge"` maps to a method named `_handle_charge`. This keeps subclasses clean — one method per state, no registration boilerplate.

The engine is intentionally minimal. It has no dependencies beyond the Python standard library and makes no assumptions about what your states do.
