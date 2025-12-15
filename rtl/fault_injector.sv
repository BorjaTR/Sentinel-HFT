// fault_injector.sv - Deterministic fault injection for simulation
//
// This module intercepts signals and injects faults at precise cycles.
// Active only when SIMULATION is defined.

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
    logic [31:0] remaining [NUM_CONFIGS];

    // Injection counter
    logic [31:0] injection_count;

    // Per-config activation logic
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 0; i < NUM_CONFIGS; i++) begin
                fault_active[i] <= 1'b0;
                remaining[i]    <= '0;
            end
            injection_count <= '0;
        end else begin
            for (int i = 0; i < NUM_CONFIGS; i++) begin
                if (config_valid[i]) begin
                    // Check if this fault should trigger
                    if (!fault_active[i] &&
                        cycle_count == configs[i].trigger_cycle) begin
                        fault_active[i] <= 1'b1;
                        remaining[i]    <= configs[i].duration_cycles;
                        injection_count <= injection_count + 1'b1;

                        // Special handling for single-shot faults
                        if (configs[i].duration_cycles == 0) begin
                            remaining[i] <= 32'd1;
                        end
                    end
                    // Decrement and deactivate
                    else if (fault_active[i]) begin
                        if (remaining[i] > 0) begin
                            remaining[i] <= remaining[i] - 1;
                        end else begin
                            fault_active[i] <= 1'b0;
                        end
                    end
                end
            end
        end
    end

    // Fault effect application
    always_comb begin
        // Defaults: pass through
        dn_valid_out    = dn_valid_in;
        dn_ready_out    = dn_ready_in;
        dn_data_out     = dn_data_in;
        fifo_full_out   = fifo_full_in;
        kill_switch_out = kill_switch_in;
        seq_no_out      = seq_no_in;
        emit_reset      = 1'b0;

        // Apply active faults
        for (int i = 0; i < NUM_CONFIGS; i++) begin
            if (fault_active[i] && config_valid[i]) begin
                case (configs[i].fault_type)
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
                        dn_data_out = dn_data_in ^ configs[i].parameter[63:0];
                    end

                    FAULT_REORDER: begin
                        // Swap with delayed sequence number
                        if (configs[i].parameter > 0) begin
                            seq_no_out = seq_no_in + configs[i].parameter[3:0];
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

    // Status output
    always_comb begin
        status.active           = |fault_active;
        status.injections_count = injection_count;
        status.cycles_remaining = '0;
        status.current_fault    = FAULT_NONE;

        // Find first active fault for status
        for (int i = 0; i < NUM_CONFIGS; i++) begin
            if (fault_active[i]) begin
                status.current_fault    = configs[i].fault_type;
                status.cycles_remaining = remaining[i];
                break;
            end
        end
    end

endmodule

`endif
