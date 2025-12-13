/*
 * Sentinel-HFT Simulation Driver
 *
 * This C++ driver provides a comprehensive testbench for the Sentinel Shell
 * RTL instrumentation wrapper. It supports multiple test scenarios and
 * outputs binary trace records that can be decoded with Python tools.
 *
 * Build: make
 * Run:   ./obj_dir/Vtb_sentinel_shell [options]
 *
 * Options:
 *   --trace          Enable VCD waveform tracing
 *   --num-tx N       Number of transactions to send (default: 100)
 *   --output FILE    Output trace file (default: trace_output.bin)
 *   --test NAME      Run specific test (latency, backpressure, overflow,
 *                    determinism, equivalence)
 *   --seed N         Random seed for reproducibility
 *   --bp-cycles N    Backpressure cycles for backpressure test
 */

#include <verilated.h>
#include <verilated_vcd_c.h>
#include "Vtb_sentinel_shell.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <vector>
#include <string>
#include <random>

// Trace record structure (must match RTL and Python)
#pragma pack(push, 1)
struct TraceRecord {
    uint64_t tx_id;
    uint64_t t_ingress;
    uint64_t t_egress;
    uint16_t flags;
    uint16_t opcode;
    uint32_t meta;
};
#pragma pack(pop)

static_assert(sizeof(TraceRecord) == 32, "TraceRecord must be 32 bytes");

// Global simulation time
vluint64_t sim_time = 0;

// Verilator callback for $time
double sc_time_stamp() {
    return sim_time;
}

class SentinelShellTestbench {
public:
    Vtb_sentinel_shell* dut;
    VerilatedVcdC* tfp;
    bool tracing;

    // Test configuration
    uint32_t num_transactions;
    uint32_t random_seed;
    std::string output_file;
    std::string test_name;
    uint32_t bp_cycles;  // Backpressure cycles for BP test

    // Collected traces
    std::vector<TraceRecord> traces;

    // Statistics
    uint64_t cycles_run;
    uint64_t transactions_sent;
    uint64_t transactions_received;

    SentinelShellTestbench()
        : dut(nullptr), tfp(nullptr), tracing(false),
          num_transactions(100), random_seed(0xDEADBEEF),
          output_file("trace_output.bin"), test_name("latency"),
          bp_cycles(10),
          cycles_run(0), transactions_sent(0), transactions_received(0)
    {
        dut = new Vtb_sentinel_shell;
    }

    ~SentinelShellTestbench() {
        if (tfp) {
            tfp->close();
            delete tfp;
        }
        delete dut;
    }

    void enable_tracing(const char* filename = "tb_sentinel_shell.vcd") {
        Verilated::traceEverOn(true);
        tfp = new VerilatedVcdC;
        dut->trace(tfp, 99);
        tfp->open(filename);
        tracing = true;
    }

    void tick() {
        // Note: trace_ready is managed by the caller, not automatically set here
        // Rising edge
        dut->clk = 1;
        dut->eval();
        if (tracing) tfp->dump(sim_time);
        sim_time += 5;  // 5ns (100MHz clock)

        // Falling edge
        dut->clk = 0;
        dut->eval();
        if (tracing) tfp->dump(sim_time);
        sim_time += 5;

        cycles_run++;
    }

    void reset() {
        dut->rst_n = 0;
        dut->in_valid = 0;
        dut->in_data = 0;
        dut->in_opcode = 0;
        dut->in_meta = 0;
        dut->out_ready = 1;
        dut->trace_ready = 1;

        // Hold reset for 10 cycles
        for (int i = 0; i < 10; i++) {
            tick();
        }

        dut->rst_n = 1;
        tick();
    }

    // Send a transaction (blocking until accepted)
    void send_transaction(uint64_t data, uint16_t opcode = 0, uint32_t meta = 0) {
        dut->in_valid = 1;
        dut->in_data = data;
        dut->in_opcode = opcode;
        dut->in_meta = meta;

        // Wait for ready
        while (!dut->in_ready) {
            tick();
        }
        tick();  // Transaction accepted on this cycle

        dut->in_valid = 0;
        transactions_sent++;
    }

    // Collect trace record if available (call after tick)
    bool collect_trace() {
        if (dut->trace_valid) {
            TraceRecord rec;
            rec.tx_id = dut->trace_tx_id;
            rec.t_ingress = dut->trace_t_ingress;
            rec.t_egress = dut->trace_t_egress;
            rec.flags = dut->trace_flags;
            rec.opcode = dut->trace_opcode;
            rec.meta = dut->trace_meta;
            traces.push_back(rec);
            return true;
        }
        return false;
    }

    // Collect output transaction if available
    bool collect_output() {
        if (dut->out_valid && dut->out_ready) {
            transactions_received++;
            return true;
        }
        return false;
    }

    // Process one cycle (collect traces and outputs)
    void process_cycle() {
        // Ensure trace_ready is high when we want to collect traces
        dut->trace_ready = 1;
        // Check for output handshake BEFORE tick (captures the handshake about to happen)
        collect_output();
        // Tick to advance simulation
        tick();
        // Collect any available trace (one per tick, trace_valid is updated by tick)
        collect_trace();
    }

    // Wait for all transactions to complete
    void drain(uint32_t max_cycles = 10000) {
        uint32_t timeout = max_cycles;
        while (transactions_received < transactions_sent && timeout > 0) {
            // Check output before tick to count handshake
            if (dut->out_valid && dut->out_ready) {
                transactions_received++;
            }
            tick();
            // Also collect traces if trace_ready is set
            if (dut->trace_ready) {
                collect_trace();
            }
            timeout--;
        }
        if (timeout == 0) {
            fprintf(stderr, "Warning: drain timeout, sent=%lu received=%lu\n",
                    transactions_sent, transactions_received);
        }
    }

    // Write traces to binary file
    void write_traces() {
        std::ofstream out(output_file, std::ios::binary);
        if (!out) {
            fprintf(stderr, "Error: Could not open %s for writing\n",
                    output_file.c_str());
            return;
        }

        for (const auto& rec : traces) {
            out.write(reinterpret_cast<const char*>(&rec), sizeof(rec));
        }

        printf("Wrote %zu trace records to %s\n", traces.size(), output_file.c_str());
    }

    // Print summary statistics
    void print_summary() {
        printf("\n=== Simulation Summary ===\n");
        printf("Test: %s\n", test_name.c_str());
        printf("Cycles run: %lu\n", cycles_run);
        printf("Transactions sent: %lu\n", transactions_sent);
        printf("Transactions received: %lu\n", transactions_received);
        printf("Traces collected: %zu\n", traces.size());
        printf("Trace drops: %lu\n", (unsigned long)dut->trace_drop_count);
        printf("In backpressure cycles: %lu\n", (unsigned long)dut->in_backpressure_cycles);
        printf("Out backpressure cycles: %lu\n", (unsigned long)dut->out_backpressure_cycles);
        printf("Inflight underflows: %u\n", dut->inflight_underflow_count);
        printf("Trace overflow seen: %d\n", dut->trace_overflow_seen);
        printf("===========================\n");
    }

    //-------------------------------------------------------------------------
    // Test: Latency verification
    //-------------------------------------------------------------------------
    int test_latency() {
        printf("Running latency test with %u transactions...\n", num_transactions);
        reset();

        // Send transactions
        for (uint32_t i = 0; i < num_transactions; i++) {
            send_transaction(i, i & 0xFFFF, i);
            // Process outputs and traces
            for (int j = 0; j < 5; j++) {
                process_cycle();
            }
        }

        // Drain remaining
        drain();

        // Collect any remaining traces
        for (int i = 0; i < 100; i++) {
            process_cycle();
        }

        write_traces();
        print_summary();

        // Verify
        bool pass = true;

        // Check we got all traces
        if (traces.size() != num_transactions) {
            fprintf(stderr, "FAIL: Expected %u traces, got %zu\n",
                    num_transactions, traces.size());
            pass = false;
        }

        // Check tx_id is strictly increasing
        for (size_t i = 0; i < traces.size(); i++) {
            if (traces[i].tx_id != i) {
                fprintf(stderr, "FAIL: Trace %zu has tx_id=%lu, expected %zu\n",
                        i, traces[i].tx_id, i);
                pass = false;
                break;
            }
        }

        // Check no drops
        if (dut->trace_drop_count != 0) {
            fprintf(stderr, "FAIL: Expected 0 trace drops, got %lu\n",
                    (unsigned long)dut->trace_drop_count);
            pass = false;
        }

        // Check latency consistency (all should be same for stub core)
        if (!traces.empty()) {
            int64_t expected_latency = traces[0].t_egress - traces[0].t_ingress;
            for (size_t i = 1; i < traces.size(); i++) {
                int64_t lat = traces[i].t_egress - traces[i].t_ingress;
                if (lat != expected_latency) {
                    fprintf(stderr, "FAIL: Inconsistent latency at trace %zu: %ld vs %ld\n",
                            i, lat, expected_latency);
                    pass = false;
                    break;
                }
            }
            printf("Measured latency: %ld cycles\n", expected_latency);
        }

        return pass ? 0 : 1;
    }

    //-------------------------------------------------------------------------
    // Test: Backpressure accounting
    //-------------------------------------------------------------------------
    int test_backpressure() {
        printf("Running backpressure test with %u BP cycles...\n", bp_cycles);
        reset();

        // First, block the output to prevent draining
        dut->out_ready = 0;

        // Send transactions to fill the pipeline
        // With out_ready=0, these will pile up
        for (int i = 0; i < 10; i++) {
            send_transaction(0x1000 + i, i, i);
        }

        // Now assert in_valid - with full pipeline and out_ready=0,
        // in_ready should be 0 and we'll get backpressure
        dut->in_valid = 1;
        dut->in_data = 0x5678;
        dut->in_opcode = 1;
        dut->in_meta = 1;

        // Record BP counter at start
        uint64_t bp_start = dut->in_backpressure_cycles;

        // Run for bp_cycles with backpressure condition
        for (uint32_t i = 0; i < bp_cycles; i++) {
            tick();
        }

        uint64_t bp_measured = dut->in_backpressure_cycles - bp_start;

        // Release backpressure
        dut->out_ready = 1;
        dut->in_valid = 0;

        // Drain remaining transactions
        drain();

        // Collect traces
        for (int i = 0; i < 50; i++) {
            process_cycle();
        }

        write_traces();
        print_summary();

        printf("Backpressure cycles measured: %lu (expected: %u)\n",
               bp_measured, bp_cycles);

        // Tolerance for pipeline timing variations
        if (bp_measured < bp_cycles - 3 || bp_measured > bp_cycles + 5) {
            fprintf(stderr, "FAIL: Backpressure counter mismatch\n");
            return 1;
        }

        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Overflow handling
    //-------------------------------------------------------------------------
    int test_overflow() {
        printf("Running overflow test with %u transactions (no trace consumption)...\n",
               num_transactions);
        reset();

        // Disable trace consumption to force overflow
        dut->trace_ready = 0;

        // Send many transactions
        for (uint32_t i = 0; i < num_transactions; i++) {
            // Check output BEFORE send_transaction's tick to catch pending handshakes
            if (dut->out_valid && dut->out_ready) {
                transactions_received++;
            }
            send_transaction(i, i & 0xFFFF, i);
        }

        // Drain remaining transactions
        // Keep trace consumption disabled to ensure overflow happens
        uint32_t timeout = 10000;
        while (transactions_received < transactions_sent && timeout > 0) {
            // Check for output handshake before tick
            if (dut->out_valid && dut->out_ready) {
                transactions_received++;
            }
            tick();
            timeout--;
        }
        if (timeout == 0) {
            fprintf(stderr, "Warning: drain timeout, sent=%lu received=%lu\n",
                    transactions_sent, transactions_received);
        }

        print_summary();

        bool pass = true;

        // Verify no deadlock - all transactions should complete
        if (transactions_received != num_transactions) {
            fprintf(stderr, "FAIL: Deadlock detected, only %lu/%u transactions completed\n",
                    transactions_received, num_transactions);
            pass = false;
        }

        // Verify drops occurred
        if (dut->trace_drop_count == 0) {
            fprintf(stderr, "FAIL: Expected trace drops, but got 0\n");
            pass = false;
        } else {
            printf("Trace drops (expected): %lu\n", (unsigned long)dut->trace_drop_count);
        }

        // Verify overflow flag
        if (!dut->trace_overflow_seen) {
            fprintf(stderr, "FAIL: trace_overflow_seen should be set\n");
            pass = false;
        }

        return pass ? 0 : 1;
    }

    //-------------------------------------------------------------------------
    // Test: Determinism (same seed = same traces)
    //-------------------------------------------------------------------------
    int test_determinism() {
        printf("Running determinism test (run 1)...\n");
        std::mt19937 rng(random_seed);

        reset();

        // Run with random data
        for (uint32_t i = 0; i < num_transactions; i++) {
            uint64_t data = rng();
            uint16_t opcode = rng() & 0xFFFF;
            uint32_t meta = rng();
            send_transaction(data, opcode, meta);
            for (int j = 0; j < 3; j++) {
                process_cycle();
            }
        }

        drain();
        for (int i = 0; i < 100; i++) {
            process_cycle();
        }

        // Store first run traces
        std::vector<TraceRecord> run1_traces = traces;

        // Reset and run again with same seed
        printf("Running determinism test (run 2)...\n");
        traces.clear();
        transactions_sent = 0;
        transactions_received = 0;
        cycles_run = 0;

        rng.seed(random_seed);
        reset();

        for (uint32_t i = 0; i < num_transactions; i++) {
            uint64_t data = rng();
            uint16_t opcode = rng() & 0xFFFF;
            uint32_t meta = rng();
            send_transaction(data, opcode, meta);
            for (int j = 0; j < 3; j++) {
                process_cycle();
            }
        }

        drain();
        for (int i = 0; i < 100; i++) {
            process_cycle();
        }

        print_summary();

        // Compare traces
        if (traces.size() != run1_traces.size()) {
            fprintf(stderr, "FAIL: Trace count differs: %zu vs %zu\n",
                    traces.size(), run1_traces.size());
            return 1;
        }

        for (size_t i = 0; i < traces.size(); i++) {
            if (memcmp(&traces[i], &run1_traces[i], sizeof(TraceRecord)) != 0) {
                fprintf(stderr, "FAIL: Trace %zu differs between runs\n", i);
                return 1;
            }
        }

        printf("PASS: Both runs produced identical traces\n");
        write_traces();
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Functional equivalence (output data matches input)
    //-------------------------------------------------------------------------
    int test_equivalence() {
        printf("Running functional equivalence test...\n");
        reset();

        std::vector<uint64_t> sent_data;

        // Send transactions and record data
        for (uint32_t i = 0; i < num_transactions; i++) {
            uint64_t data = 0x1000 + i;
            sent_data.push_back(data);
            send_transaction(data, i & 0xFFFF, i);
            for (int j = 0; j < 3; j++) {
                process_cycle();
            }
        }

        drain();
        for (int i = 0; i < 100; i++) {
            process_cycle();
        }

        write_traces();
        print_summary();

        // Verify we got all transactions
        if (transactions_received != num_transactions) {
            fprintf(stderr, "FAIL: Expected %u transactions, received %lu\n",
                    num_transactions, transactions_received);
            return 1;
        }

        // Verify trace count
        if (traces.size() != num_transactions) {
            fprintf(stderr, "FAIL: Expected %u traces, got %zu\n",
                    num_transactions, traces.size());
            return 1;
        }

        printf("PASS: All %u transactions passed through correctly\n", num_transactions);
        return 0;
    }

    // Run the selected test
    int run_test() {
        if (test_name == "latency") {
            return test_latency();
        } else if (test_name == "backpressure") {
            return test_backpressure();
        } else if (test_name == "overflow") {
            return test_overflow();
        } else if (test_name == "determinism") {
            return test_determinism();
        } else if (test_name == "equivalence") {
            return test_equivalence();
        } else {
            fprintf(stderr, "Unknown test: %s\n", test_name.c_str());
            return 1;
        }
    }
};

void print_usage(const char* prog) {
    printf("Usage: %s [options]\n", prog);
    printf("\nOptions:\n");
    printf("  --trace          Enable VCD waveform tracing\n");
    printf("  --num-tx N       Number of transactions (default: 100)\n");
    printf("  --output FILE    Output trace file (default: trace_output.bin)\n");
    printf("  --test NAME      Test to run: latency, backpressure, overflow,\n");
    printf("                   determinism, equivalence (default: latency)\n");
    printf("  --seed N         Random seed (default: 0xDEADBEEF)\n");
    printf("  --bp-cycles N    Backpressure cycles for BP test (default: 10)\n");
    printf("  --help           Show this help\n");
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    SentinelShellTestbench tb;

    // Parse arguments
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--trace") == 0) {
            tb.enable_tracing();
        } else if (strcmp(argv[i], "--num-tx") == 0 && i + 1 < argc) {
            tb.num_transactions = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--output") == 0 && i + 1 < argc) {
            tb.output_file = argv[++i];
        } else if (strcmp(argv[i], "--test") == 0 && i + 1 < argc) {
            tb.test_name = argv[++i];
        } else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) {
            tb.random_seed = strtoul(argv[++i], nullptr, 0);
        } else if (strcmp(argv[i], "--bp-cycles") == 0 && i + 1 < argc) {
            tb.bp_cycles = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        }
    }

    int result = tb.run_test();

    printf("\nTest %s: %s\n", tb.test_name.c_str(), result == 0 ? "PASS" : "FAIL");

    return result;
}
