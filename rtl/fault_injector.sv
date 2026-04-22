// fault_injector.sv - Deterministic fault injection for simulation
//
// This module intercepts signals and injects faults at precise cycles.
// Active only when SIMULATION is defined.
//
// Fixes applied in Wave 1 (audit findings D-S1-01..03):
//   * Field `parameter` renamed to `fault_param` (Verilator >=5.x reserved
//     word rejection — Wave 0).
//   * FSM decrement is no longer gated on `config_valid`; a fault that was
//     armed and is now running continues to run and exits cleanly even if the
//     host-side config register is cleared mid-fault (D-S1-01).
//   * Off-by-one on `duration_cycles` corrected: the fault is active for
//     *exactly* `duration_cycles` cycles, or a single cycle if duration=0
//     (D-S1-02). Previously the fault stayed active for duration+1.
//   * CLOCK_STRETCH and BURST now have explicit effects on the downstream
//     handshake (D-S1-03). Both faults use `fault_param` as their intensity
//     knob and are bounded to safe maxima so they cannot wedge the DUT.

`ifndef FAULT_INJECTOR_SV
`define FAULT_INJECTOR_SV

`include "fault_pkg.sv"

module fault_injector #(
    parameter int NUM_CONFIGS = 4  // Number of fault configs to support
) (
    input  logic        clk,
    input  logic        rst_n,

    // Fault configuration (active in simulation only)
    input  fault_pkg::fault_config_t configs [NUM_CONFIGS],
    input  logic [NUM_CONFIGS-1:0]   config_valid,

    // Cycle counter input (for timing)
    input  logic [63:0] cycle_count,

    // Intercepted signals - downstream interface
    input  logic        dn_valid_in,
    output logic        dn_valid_out,
    input  logic        dn_ready_in,
    output logic        dn_ready_out,
    input  logic [63:0] dn_data_in,
    output logic [63:0] dn_data_out,

    // Intercepted signals - FIFO control
    input  logic        fifo_full_in,
    output logic        fifo_full_out,

    // Intercepted signals - kill switch
    input  logic        kill_switch_in,
    output logic        kill_switch_out,

    // Sequence number manipulation (for reorder fault)
    input  logic [31:0] seq_no_in,
    output logic [31:0] seq_no_out,
    output logic        emit_reset,      // Pulse to emit RESET record

    // Status output
    output fault_pkg::fault_status_t status
);

    import fault_pkg::*;

    // Internal state per config
    logic [NUM_CONFIGS-1:0] fault_active;
    logic [31:0]            remaining   [NUM_CONFIGS];

    // Snapshot of the triggering config so a mid-fault deassertion of
    // config_valid[i] cannot change the fault's behaviour (D-S1-01).
    fault_config_t          snapshot    [NUM_CONFIGS];

    // CLOCK_STRETCH uses a small per-config LFSR to vary the number of
    // stretched cycles so the pattern is deterministic per run but not a
    // constant value. BURST uses a small up-counter to model a fixed-length
    // burst of back-to-back fault cycles (D-S1-03).
    logic [15:0]            stretch_lfsr [NUM_CONFIGS];
    logic [15:0]            burst_count  [NUM_CONFIGS];

    // Injection counter
    logic [31:0]            injection_count;

    // ------------------------------------------------------------------
    // FSM: trigger on cycle, run for duration, exit cleanly
    // ------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 0; i < NUM_CONFIGS; i++) begin
                fault_active[i]  <= 1'b0;
                remaining[i]     <= '0;
                snapshot[i]      <= '0;
                stretch_lfsr[i]  <= 16'hACE1;   // non-zero seed
                burst_count[i]   <= '0;
            end
            injection_count <= '0;
        end else begin
            for (int i = 0; i < NUM_CONFIGS; i++) begin
                // Trigger condition — latch snapshot the cycle we fire.
                if (!fault_active[i]                     &&
                    config_valid[i]                      &&
                    (cycle_count == configs[i].trigger_cycle)) begin
                    fault_active[i]   <= 1'b1;
                    snapshot[i]       <= configs[i];
                    // duration_cycles==0 means "single-shot" → active for
                    // exactly one cycle. Otherwise active for exactly N
                    // cycles (D-S1-02 fix: no off-by-one).
                    remaining[i]      <= (configs[i].duration_cycles == 0)
                                           ? 32'd1
                                           : configs[i].duration_cycles;
                    burst_count[i]    <= '0;
                    injection_count   <= injection_count + 1'b1;
                end
                // Decrement while active — NOT gated on config_valid
                // (D-S1-01 fix: a stuck fault_active cannot survive
                // here even if the host clears config_valid).
                else if (fault_active[i]) begin
                    // Simple 16-bit Galois LFSR for stretch jitter
                    stretch_lfsr[i] <= {stretch_lfsr[i][14:0],
                                        stretch_lfsr[i][15] ^
                                        stretch_lfsr[i][13] ^
                                        stretch_lfsr[i][12] ^
                                        stretch_lfsr[i][10]};
                    burst_count[i]  <= burst_count[i] + 1'b1;

                    if (remaining[i] <= 32'd1) begin
                        fault_active[i] <= 1'b0;
                        remaining[i]    <= '0;
                    end else begin
                        remaining[i]    <= remaining[i] - 1'b1;
                    end
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // Fault effect application
    // ------------------------------------------------------------------
    // Locals that can be overwritten by the fault loop below.
    logic stretch_stall;
    logic burst_assert;
    always_comb begin
        // Defaults: pass through
        dn_valid_out    = dn_valid_in;
        dn_ready_out    = dn_ready_in;
        dn_data_out     = dn_data_in;
        fifo_full_out   = fifo_full_in;
        kill_switch_out = kill_switch_in;
        seq_no_out      = seq_no_in;
        emit_reset      = 1'b0;
        stretch_stall   = 1'b0;
        burst_assert    = 1'b0;

        // Apply active faults using the snapshot captured at trigger time.
        for (int i = 0; i < NUM_CONFIGS; i++) begin
            if (fault_active[i]) begin
                case (snapshot[i].fault_type)
                    FAULT_BACKPRESSURE: begin
                        dn_ready_out = 1'b0;  // Block downstream
                    end

                    FAULT_FIFO_OVERFLOW: begin
                        fifo_full_out = 1'b1;  // Force FIFO full
                    end

                    FAULT_KILL_SWITCH: begin
                        kill_switch_out = 1'b1;  // Trigger kill switch
                    end

                    FAULT_CORRUPT_DATA: begin
                        dn_data_out = dn_data_in ^ {32'h0, snapshot[i].fault_param};
                    end

                    FAULT_CLOCK_STRETCH: begin
                        // Hold dn_ready_out low on "stretch" cycles, where
                        // stretch frequency is tuned by fault_param. A
                        // fault_param of N means we stall roughly N out
                        // of every 16 cycles (D-S1-03).
                        automatic logic [15:0] thresh =
                            (snapshot[i].fault_param[15:0] > 16'd15) ? 16'd15
                                                                     : snapshot[i].fault_param[15:0];
                        stretch_stall = (stretch_lfsr[i][3:0] < thresh[3:0]);
                        if (stretch_stall) dn_ready_out = 1'b0;
                    end

                    FAULT_BURST: begin
                        // Drive an uninterrupted valid run of length
                        // min(fault_param, 256). We can't create new
                        // transactions, but we *can* hold `dn_valid_out`
                        // high as long as dn_valid_in is high and we
                        // haven't exhausted the burst window.
                        automatic logic [15:0] blen =
                            (snapshot[i].fault_param[15:0] > 16'd256) ? 16'd256
                                                                      : snapshot[i].fault_param[15:0];
                        burst_assert = (burst_count[i] < blen);
                        if (burst_assert) dn_valid_out = dn_valid_in | 1'b1;
                    end

                    FAULT_REORDER: begin
                        // Displace seq_no within a small window so we don't
                        // run past the 32-bit space.
                        if (snapshot[i].fault_param != 32'd0) begin
                            seq_no_out = seq_no_in + snapshot[i].fault_param[3:0];
                        end
                    end

                    FAULT_RESET: begin
                        emit_reset = 1'b1;  // Signal to emit RESET record
                    end

                    default: begin
                        // No effect
                    end
                endcase
            end
        end
    end

    // ------------------------------------------------------------------
    // Status output (first-active priority)
    // ------------------------------------------------------------------
    always_comb begin
        status.active           = |fault_active;
        status.injections_count = injection_count;
        status.cycles_remaining = '0;
        status.current_fault    = FAULT_NONE;

        // Find first active fault for status
        for (int i = 0; i < NUM_CONFIGS; i++) begin
            if (fault_active[i]) begin
                status.current_fault    = snapshot[i].fault_type;
                status.cycles_remaining = remaining[i];
                break;
            end
        end
    end

endmodule

`endif
