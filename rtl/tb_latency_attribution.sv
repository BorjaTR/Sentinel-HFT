// tb_latency_attribution.sv - Testbench for v1.2 latency attribution
//
// Verifies:
// 1. Stage deltas are non-negative
// 2. Sum of deltas <= total latency (overhead is the gap)
// 3. Attribution values are plausible
// 4. Records decode correctly

`timescale 1ns/1ps

module tb_latency_attribution;

    import trace_pkg_v12::*;

    // Parameters
    localparam int CORE_LATENCY = 10;
    localparam int RISK_LATENCY = 5;
    localparam int CLK_PERIOD   = 10;

    // Signals
    logic        clk;
    logic        rst_n;
    logic        up_valid;
    logic        up_ready;
    logic [63:0] up_data;
    logic        dn_valid;
    logic        dn_ready;
    logic [63:0] dn_data;
    logic        trace_valid;
    logic        trace_ready;
    logic [511:0] trace_data;
    logic [6:0]  trace_size;
    logic [31:0] seq_no;
    logic [31:0] drop_count;

    // DUT
    sentinel_shell_v12 #(
        .CORE_LATENCY(CORE_LATENCY),
        .RISK_LATENCY(RISK_LATENCY),
        .FIFO_DEPTH(16),
        .EMIT_V12(1),
        .CORE_ID(1)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .up_valid(up_valid),
        .up_ready(up_ready),
        .up_data(up_data),
        .dn_valid(dn_valid),
        .dn_ready(dn_ready),
        .dn_data(dn_data),
        .trace_valid(trace_valid),
        .trace_ready(trace_ready),
        .trace_data(trace_data),
        .trace_size(trace_size),
        .seq_no(seq_no),
        .trace_drop_count(drop_count)
    );

    // Clock generation
    initial begin
        clk = 0;
        forever #(CLK_PERIOD/2) clk = ~clk;
    end

    // Test counters
    int transactions_sent;
    int traces_received;
    int attribution_errors;

    // Trace record extraction
    trace_record_v12_t received_record;

    always_comb begin
        received_record = trace_data;
    end

    // Main test sequence
    initial begin
        // Initialize
        rst_n       = 0;
        up_valid    = 0;
        up_data     = 0;
        dn_ready    = 1;
        trace_ready = 1;
        transactions_sent  = 0;
        traces_received    = 0;
        attribution_errors = 0;

        // Reset
        repeat(5) @(posedge clk);
        rst_n = 1;
        repeat(5) @(posedge clk);

        // Send 100 transactions
        for (int i = 0; i < 100; i++) begin
            // Send transaction
            @(posedge clk);
            up_valid = 1;
            up_data  = 64'hDEADBEEF_00000000 | i;

            // Wait for acceptance
            while (!up_ready) @(posedge clk);
            @(posedge clk);
            up_valid = 0;
            transactions_sent++;

            // Wait for completion
            while (!dn_valid) @(posedge clk);
            @(posedge clk);
        end

        // Drain traces
        repeat(50) @(posedge clk);

        // Report
        $display("========================================");
        $display("Test Complete");
        $display("  Transactions sent:   %0d", transactions_sent);
        $display("  Traces received:     %0d", traces_received);
        $display("  Attribution errors:  %0d", attribution_errors);
        $display("  Drops:               %0d", drop_count);
        $display("========================================");

        if (attribution_errors == 0 && traces_received == transactions_sent)
            $display("PASS");
        else
            $display("FAIL");

        $finish;
    end

    // Trace validation
    always @(posedge clk) begin
        if (trace_valid && trace_ready) begin
            traces_received++;

            // Check record format
            if (trace_size != 64) begin
                $display("ERROR: Expected 64-byte record, got %0d", trace_size);
                attribution_errors++;
            end

            // Check version
            if (received_record.version != 8'h02) begin
                $display("ERROR: Expected version 0x02, got 0x%02x", received_record.version);
                attribution_errors++;
            end

            // Check deltas are non-negative (always true for unsigned, but check plausibility)
            if (received_record.d_ingress == 0 && received_record.d_core == 0) begin
                $display("ERROR: All deltas are zero - attribution not captured");
                attribution_errors++;
            end

            // Check sum of deltas <= total latency
            automatic logic [63:0] total_latency = received_record.t_egress - received_record.t_ingress;
            automatic logic [63:0] sum_deltas = received_record.d_ingress +
                                                received_record.d_core +
                                                received_record.d_risk +
                                                received_record.d_egress;

            if (sum_deltas > total_latency) begin
                $display("ERROR: Sum of deltas (%0d) > total latency (%0d)", sum_deltas, total_latency);
                attribution_errors++;
            end

            // Check core latency is approximately CORE_LATENCY
            if (received_record.d_core < CORE_LATENCY - 2 || received_record.d_core > CORE_LATENCY + 2) begin
                $display("WARNING: d_core=%0d, expected ~%0d", received_record.d_core, CORE_LATENCY);
            end

            // Check risk latency is approximately RISK_LATENCY
            if (received_record.d_risk < RISK_LATENCY - 2 || received_record.d_risk > RISK_LATENCY + 2) begin
                $display("WARNING: d_risk=%0d, expected ~%0d", received_record.d_risk, RISK_LATENCY);
            end

            // Print attribution for first few records
            if (traces_received <= 5) begin
                $display("Trace %0d: total=%0d, ingress=%0d, core=%0d, risk=%0d, egress=%0d, overhead=%0d",
                    traces_received,
                    total_latency,
                    received_record.d_ingress,
                    received_record.d_core,
                    received_record.d_risk,
                    received_record.d_egress,
                    total_latency - sum_deltas
                );
            end
        end
    end

endmodule
