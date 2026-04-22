// fault_pkg.sv - Fault injection types and configuration
//
// Defines the fault types that can be injected into the simulation
// for testing system robustness.

`ifndef FAULT_PKG_SV
`define FAULT_PKG_SV

package fault_pkg;

    // Fault type enumeration
    typedef enum logic [3:0] {
        FAULT_NONE           = 4'b0000,  // No fault
        FAULT_BACKPRESSURE   = 4'b0001,  // Hold downstream ready low
        FAULT_FIFO_OVERFLOW  = 4'b0010,  // Force trace FIFO full
        FAULT_KILL_SWITCH    = 4'b0011,  // Trigger kill switch
        FAULT_CORRUPT_DATA   = 4'b0100,  // Flip data bits
        FAULT_CLOCK_STRETCH  = 4'b0101,  // Add variable latency
        FAULT_BURST          = 4'b0110,  // Inject traffic burst
        FAULT_REORDER        = 4'b0111,  // Emit seq_no out of order
        FAULT_RESET          = 4'b1000   // Emit RESET record
    } fault_type_t;

    // Fault configuration
    //
    // NOTE: The field below is named `fault_param`, not `parameter`, because
    // `parameter` is a reserved word in SystemVerilog-2012/2017 and is rejected
    // by Verilator >=5.x and modern Vivado. Earlier drafts of this package used
    // the reserved word, which elaborated under the older Verilator 4.x we were
    // pinned to but breaks every modern tool.
    typedef struct packed {
        fault_type_t fault_type;       // Type of fault to inject
        logic [31:0] trigger_cycle;    // Cycle to start injection
        logic [31:0] duration_cycles;  // Duration (0 = single shot)
        logic [31:0] fault_param;      // Fault-specific parameter
        // Parameters by fault type:
        //   BACKPRESSURE:  fault_param = ignored
        //   FIFO_OVERFLOW: fault_param = ignored
        //   KILL_SWITCH:   fault_param = ignored
        //   CORRUPT_DATA:  fault_param = bit mask
        //   CLOCK_STRETCH: fault_param = max additional cycles
        //   BURST:         fault_param = burst size (transactions)
        //   REORDER:       fault_param = max displacement
        //   RESET:         fault_param = ignored
    } fault_config_t;

    // Fault status (output from injector)
    typedef struct packed {
        logic        active;           // Fault currently being injected
        fault_type_t current_fault;    // Which fault is active
        logic [31:0] cycles_remaining; // Cycles until fault ends
        logic [31:0] injections_count; // Total injections performed
    } fault_status_t;

    // Maximum number of simultaneous fault configs
    localparam int MAX_FAULT_CONFIGS = 8;

endpackage

`endif
