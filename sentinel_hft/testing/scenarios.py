"""
scenarios.py - Built-in fault injection scenarios

These scenarios cover critical failure modes that should be tested
before any deployment.
"""

from .fault_injection import (
    FaultScenario,
    FaultConfig,
    FaultType,
    ExpectedBehavior,
)


# Standard scenarios for testing
SCENARIOS = {
    "backpressure_storm": FaultScenario(
        name="backpressure_storm",
        description=(
            "Downstream system holds ready low for 1000 cycles, simulating "
            "a slow consumer. The system should buffer traces and drop "
            "gracefully if FIFO fills."
        ),
        faults=[
            FaultConfig(
                fault_type=FaultType.BACKPRESSURE,
                trigger_cycle=1000,
                duration_cycles=1000,
            ),
        ],
        expected=ExpectedBehavior(
            min_drops=0,
            max_drops=100,
            should_trigger_kill_switch=False,
            max_latency_spike_factor=5.0,
        ),
    ),

    "fifo_overflow": FaultScenario(
        name="fifo_overflow",
        description=(
            "Force the trace FIFO full for 200 cycles. Verifies graceful "
            "degradation where traces are dropped but pipeline continues."
        ),
        faults=[
            FaultConfig(
                fault_type=FaultType.FIFO_OVERFLOW,
                trigger_cycle=500,
                duration_cycles=200,
            ),
        ],
        expected=ExpectedBehavior(
            min_drops=10,
            max_drops=100,
            should_trigger_kill_switch=False,
        ),
    ),

    "kill_switch_trigger": FaultScenario(
        name="kill_switch_trigger",
        description=(
            "Trigger the kill switch as if loss threshold was exceeded. "
            "All trading should halt immediately."
        ),
        faults=[
            FaultConfig(
                fault_type=FaultType.KILL_SWITCH,
                trigger_cycle=2000,
                duration_cycles=0,  # Latching
            ),
        ],
        expected=ExpectedBehavior(
            should_trigger_kill_switch=True,
        ),
    ),

    "cascading_failure": FaultScenario(
        name="cascading_failure",
        description=(
            "Backpressure combined with traffic burst, simulating a "
            "realistic overload scenario. Tests compound failure handling."
        ),
        faults=[
            FaultConfig(
                fault_type=FaultType.BACKPRESSURE,
                trigger_cycle=1000,
                duration_cycles=500,
            ),
            FaultConfig(
                fault_type=FaultType.BURST,
                trigger_cycle=1200,
                duration_cycles=300,
                parameter=100,  # 100 extra transactions
            ),
        ],
        expected=ExpectedBehavior(
            min_drops=20,
            max_drops=200,
            max_latency_spike_factor=10.0,
        ),
    ),

    # === HOSTILE INPUT SCENARIOS ===

    "reorder_burst": FaultScenario(
        name="reorder_burst",
        description=(
            "Inject sequence numbers out of order, simulating network "
            "reordering. The SequenceTracker should detect reordering "
            "but NOT count it as drops."
        ),
        faults=[
            FaultConfig(
                fault_type=FaultType.REORDER,
                trigger_cycle=800,
                duration_cycles=100,
                parameter=5,  # Max 5 positions out of order
            ),
        ],
        expected=ExpectedBehavior(
            reorder_detected=True,
            metrics_uncorrupted=True,
            max_false_drops=0,  # Reorder != drop
        ),
    ),

    "reset_mid_stream": FaultScenario(
        name="reset_mid_stream",
        description=(
            "Emit a RESET record and restart sequence numbers at 0. "
            "Simulates FPGA reconfiguration or firmware update. "
            "Must NOT report billions of drops."
        ),
        faults=[
            FaultConfig(
                fault_type=FaultType.RESET,
                trigger_cycle=1500,
                duration_cycles=0,
            ),
        ],
        expected=ExpectedBehavior(
            reset_handled=True,
            max_false_drops=0,
        ),
    ),
}


def get_scenario(name: str) -> FaultScenario:
    """Get a scenario by name."""
    if name not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario: {name}. "
            f"Available: {', '.join(SCENARIOS.keys())}"
        )
    return SCENARIOS[name]


def list_scenarios() -> list:
    """List all available scenario names."""
    return list(SCENARIOS.keys())
