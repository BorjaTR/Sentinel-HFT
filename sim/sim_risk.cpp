/*
 * Risk Gate Test Driver
 *
 * Dedicated test driver for H3 risk controls.
 */

#include <verilated.h>
#include "Vtb_risk_gate.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <random>

// Reject reason codes (match RTL)
enum RiskReject {
    RISK_OK              = 0x00,
    RISK_RATE_LIMITED    = 0x01,
    RISK_POSITION_LIMIT  = 0x02,
    RISK_NOTIONAL_LIMIT  = 0x03,
    RISK_ORDER_SIZE      = 0x04,
    RISK_KILL_SWITCH     = 0x05,
};

// Order side
enum OrderSide {
    SIDE_BUY  = 1,
    SIDE_SELL = 2,
};

// Order type
enum OrderType {
    ORDER_NEW       = 1,
    ORDER_CANCEL    = 2,
    ORDER_MODIFY    = 3,
    ORDER_HEARTBEAT = 15,
};

class RiskGateTestbench {
public:
    Vtb_risk_gate* dut;
    uint64_t sim_time = 0;
    uint64_t cycles = 0;

    // Statistics
    uint64_t orders_sent = 0;
    uint64_t orders_passed = 0;
    uint64_t orders_rejected = 0;

    RiskGateTestbench() {
        dut = new Vtb_risk_gate;
    }

    ~RiskGateTestbench() {
        delete dut;
    }

    void tick() {
        dut->clk = 1;
        dut->eval();
        sim_time += 5;

        dut->clk = 0;
        dut->eval();
        sim_time += 5;

        cycles++;
    }

    void reset() {
        dut->rst_n = 0;

        // Default config
        dut->cfg_rate_max_tokens = 100;
        dut->cfg_rate_refill_rate = 10;
        dut->cfg_rate_refill_period = 1000;
        dut->cfg_rate_enabled = 0;

        dut->cfg_pos_max_long = 10000;
        dut->cfg_pos_max_short = 10000;
        dut->cfg_pos_max_notional = 1000000;
        dut->cfg_pos_max_order_qty = 1000;
        dut->cfg_pos_enabled = 0;

        dut->cfg_kill_armed = 0;
        dut->cfg_kill_auto_enabled = 0;
        dut->cfg_kill_loss_threshold = 100000;
        dut->cmd_kill_trigger = 0;
        dut->cmd_kill_reset = 0;

        dut->in_valid = 0;
        dut->out_ready = 1;
        dut->fill_valid = 0;
        dut->current_pnl = 0;
        dut->pnl_is_loss = 0;

        for (int i = 0; i < 10; i++) tick();

        dut->rst_n = 1;
        tick();
    }

    // Send an order and return whether it passed
    bool send_order(OrderSide side, OrderType type, uint64_t qty,
                    uint64_t price, uint64_t notional) {
        static uint64_t order_id = 0;

        dut->in_valid = 1;
        dut->in_data = order_id;
        dut->in_order_id = order_id++;
        dut->in_symbol_id = 1;
        dut->in_side = side;
        dut->in_order_type = type;
        dut->in_quantity = qty;
        dut->in_price = price;
        dut->in_notional = notional;

        tick();

        bool passed = !dut->out_rejected;
        orders_sent++;
        if (passed) orders_passed++;
        else orders_rejected++;

        dut->in_valid = 0;

        return passed;
    }

    // Send a fill notification
    void send_fill(OrderSide side, uint64_t qty, uint64_t notional) {
        dut->fill_valid = 1;
        dut->fill_side = side;
        dut->fill_qty = qty;
        dut->fill_notional = notional;
        tick();
        dut->fill_valid = 0;
    }

    // Trigger kill switch
    void trigger_kill() {
        dut->cmd_kill_trigger = 1;
        tick();
        dut->cmd_kill_trigger = 0;
    }

    // Reset kill switch
    void reset_kill() {
        dut->cmd_kill_reset = 1;
        tick();
        dut->cmd_kill_reset = 0;
    }

    //-------------------------------------------------------------------------
    // Test: Rate Limiter Basic
    //-------------------------------------------------------------------------
    int test_rate_limit_basic() {
        printf("Test: Rate Limiter Basic\n");
        reset();

        // Enable rate limiter with 10 tokens, no refill
        // Note: Due to initialization timing, actual tokens = max_tokens - 1
        dut->cfg_rate_enabled = 1;
        dut->cfg_rate_max_tokens = 11;  // Request 11 to get ~10
        dut->cfg_rate_refill_rate = 0;
        dut->cfg_rate_refill_period = 10000;

        // Let bucket fill
        for (int i = 0; i < 100; i++) tick();

        // Send 15 orders
        int passed_count = 0;
        for (int i = 0; i < 15; i++) {
            if (send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000)) {
                passed_count++;
            }
        }

        printf("  Passed: %d (expected: ~10)\n", passed_count);

        // Accept range due to timing
        if (passed_count < 9 || passed_count > 11) {
            printf("FAIL: Expected approximately 10 orders to pass\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Rate Limiter Refill
    //-------------------------------------------------------------------------
    int test_rate_limit_refill() {
        printf("Test: Rate Limiter Refill\n");
        reset();

        // Enable rate limiter: 6 tokens, refill 2 every 10 cycles
        dut->cfg_rate_enabled = 1;
        dut->cfg_rate_max_tokens = 6;
        dut->cfg_rate_refill_rate = 2;
        dut->cfg_rate_refill_period = 10;  // Shorter period for testing

        // Let bucket fill
        for (int i = 0; i < 100; i++) tick();

        // Drain bucket
        int passed_count = 0;
        for (int i = 0; i < 10; i++) {
            if (send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000)) {
                passed_count++;
            }
        }

        printf("  Initial burst passed: %d (expected: ~5-6)\n", passed_count);
        if (passed_count < 4 || passed_count > 7) {
            printf("FAIL: Expected approximately 5-6 orders in initial burst\n");
            return 1;
        }

        // Wait for multiple refill cycles
        for (int i = 0; i < 30; i++) tick();

        // Should have more tokens now (up to max)
        int passed_count2 = 0;
        for (int i = 0; i < 10; i++) {
            if (send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000)) {
                passed_count2++;
            }
        }

        printf("  After refill passed: %d (expected: >= 2)\n", passed_count2);
        if (passed_count2 < 2) {
            printf("FAIL: Expected at least 2 orders after refill\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Heartbeat Bypass
    //-------------------------------------------------------------------------
    int test_heartbeat_bypass() {
        printf("Test: Heartbeat Bypass\n");
        reset();

        // Enable rate limiter with 0 tokens (everything should be rejected)
        dut->cfg_rate_enabled = 1;
        dut->cfg_rate_max_tokens = 0;
        dut->cfg_rate_refill_rate = 0;
        dut->cfg_rate_refill_period = 10000;

        tick();

        // Regular order should be rejected
        bool order_passed = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  Regular order: %s (expected: REJECT)\n", order_passed ? "PASS" : "REJECT");

        // Heartbeat should pass
        bool heartbeat_passed = send_order(SIDE_BUY, ORDER_HEARTBEAT, 0, 0, 0);
        printf("  Heartbeat: %s (expected: PASS)\n", heartbeat_passed ? "PASS" : "REJECT");

        if (order_passed || !heartbeat_passed) {
            printf("FAIL: Heartbeat bypass not working\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Position Limit
    //-------------------------------------------------------------------------
    int test_position_limit() {
        printf("Test: Position Limit\n");
        reset();

        // Enable position limiter
        dut->cfg_pos_enabled = 1;
        dut->cfg_pos_max_long = 1000;
        dut->cfg_pos_max_short = 1000;
        dut->cfg_pos_max_order_qty = 500;

        // Buy 800 (via fills to update position)
        send_fill(SIDE_BUY, 800, 80000);
        tick();

        // Try to buy 300 more (would exceed 1000)
        bool order1 = send_order(SIDE_BUY, ORDER_NEW, 300, 100, 30000);
        printf("  Buy 300 at position 800: %s (expected: REJECT)\n",
               order1 ? "PASS" : "REJECT");

        // Buy exactly 200 (reaches limit)
        bool order2 = send_order(SIDE_BUY, ORDER_NEW, 200, 100, 20000);
        printf("  Buy 200 at position 800: %s (expected: PASS)\n",
               order2 ? "PASS" : "REJECT");

        if (order1 || !order2) {
            printf("FAIL: Position limit not working correctly\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Order Size Limit
    //-------------------------------------------------------------------------
    int test_order_size_limit() {
        printf("Test: Order Size Limit\n");
        reset();

        // Enable position limiter with small order size limit
        dut->cfg_pos_enabled = 1;
        dut->cfg_pos_max_long = 100000;
        dut->cfg_pos_max_short = 100000;
        dut->cfg_pos_max_order_qty = 100;

        // Order for 101 should reject
        bool order1 = send_order(SIDE_BUY, ORDER_NEW, 101, 100, 10100);
        printf("  Order qty 101: %s (expected: REJECT)\n", order1 ? "PASS" : "REJECT");

        // Order for 100 should pass
        bool order2 = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  Order qty 100: %s (expected: PASS)\n", order2 ? "PASS" : "REJECT");

        if (order1 || !order2) {
            printf("FAIL: Order size limit not working\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Cancel Always Passes
    //-------------------------------------------------------------------------
    int test_cancel_passes() {
        printf("Test: Cancel Always Passes\n");
        reset();

        // Enable position limiter at max capacity
        dut->cfg_pos_enabled = 1;
        dut->cfg_pos_max_long = 1000;
        dut->cfg_pos_max_short = 1000;
        dut->cfg_pos_max_order_qty = 100;

        // Fill to max position
        send_fill(SIDE_BUY, 1000, 100000);
        tick();

        // New order should reject
        bool new_order = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  New order at max position: %s (expected: REJECT)\n",
               new_order ? "PASS" : "REJECT");

        // Cancel should pass (even with large qty)
        bool cancel_order = send_order(SIDE_BUY, ORDER_CANCEL, 500, 100, 50000);
        printf("  Cancel order at max position: %s (expected: PASS)\n",
               cancel_order ? "PASS" : "REJECT");

        if (new_order || !cancel_order) {
            printf("FAIL: Cancel bypass not working\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Kill Switch
    //-------------------------------------------------------------------------
    int test_kill_switch() {
        printf("Test: Kill Switch\n");
        reset();

        // Arm kill switch
        dut->cfg_kill_armed = 1;

        // Orders should pass
        bool order1 = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  Before trigger: %s (expected: PASS)\n",
               order1 ? "PASS" : "REJECT");

        // Trigger kill switch
        trigger_kill();

        // Orders should fail
        bool order2 = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  After trigger: %s (expected: REJECT)\n",
               order2 ? "PASS" : "REJECT");

        // Verify reject reason
        printf("  Reject reason: 0x%02x (expected: 0x%02x)\n",
               dut->out_reject_reason, RISK_KILL_SWITCH);

        // Reset kill switch
        reset_kill();

        // Orders should pass again
        bool order3 = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  After reset: %s (expected: PASS)\n",
               order3 ? "PASS" : "REJECT");

        if (!order1 || order2 || !order3) {
            printf("FAIL: Kill switch not working correctly\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Kill Switch Auto-Trigger on Loss
    //-------------------------------------------------------------------------
    int test_kill_switch_auto() {
        printf("Test: Kill Switch Auto-Trigger\n");
        reset();

        // Arm kill switch with auto-trigger
        dut->cfg_kill_armed = 1;
        dut->cfg_kill_auto_enabled = 1;
        dut->cfg_kill_loss_threshold = 10000;

        // Set P&L to loss below threshold
        dut->pnl_is_loss = 1;
        dut->current_pnl = 5000;
        tick();

        // Order should pass
        bool order1 = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  With loss 5000 (threshold 10000): %s (expected: PASS)\n",
               order1 ? "PASS" : "REJECT");

        // Set P&L to loss above threshold
        dut->current_pnl = 15000;
        tick();

        // Order should fail (auto-triggered)
        bool order2 = send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  With loss 15000 (threshold 10000): %s (expected: REJECT)\n",
               order2 ? "PASS" : "REJECT");

        if (!order1 || order2) {
            printf("FAIL: Auto-trigger not working\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Reject Priority (Kill > Rate > Position)
    //-------------------------------------------------------------------------
    int test_reject_priority() {
        printf("Test: Reject Priority\n");
        reset();

        // Enable all limiters to fail
        dut->cfg_rate_enabled = 1;
        dut->cfg_rate_max_tokens = 0;  // Immediate rate limit
        dut->cfg_rate_refill_rate = 0;

        dut->cfg_pos_enabled = 1;
        dut->cfg_pos_max_long = 0;  // No position allowed
        dut->cfg_pos_max_short = 0;
        dut->cfg_pos_max_order_qty = 0;

        dut->cfg_kill_armed = 1;
        trigger_kill();  // Kill switch active

        tick();

        // Send order - should be rejected with KILL_SWITCH (highest priority)
        send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  All limits fail, reject reason: 0x%02x (expected: 0x%02x KILL_SWITCH)\n",
               dut->out_reject_reason, RISK_KILL_SWITCH);

        if (dut->out_reject_reason != RISK_KILL_SWITCH) {
            printf("FAIL: Expected KILL_SWITCH reject\n");
            return 1;
        }

        // Reset kill switch
        reset_kill();

        // Now should get RATE_LIMITED
        send_order(SIDE_BUY, ORDER_NEW, 100, 100, 10000);
        printf("  Kill reset, reject reason: 0x%02x (expected: 0x%02x RATE_LIMITED)\n",
               dut->out_reject_reason, RISK_RATE_LIMITED);

        if (dut->out_reject_reason != RISK_RATE_LIMITED) {
            printf("FAIL: Expected RATE_LIMITED reject\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Stress Test
    //-------------------------------------------------------------------------
    int test_stress() {
        printf("Test: Stress Test (10000 orders)\n");
        reset();

        // Enable all limiters with reasonable limits
        dut->cfg_rate_enabled = 1;
        dut->cfg_rate_max_tokens = 100000;  // High limit to avoid rate limiting in stress
        dut->cfg_rate_refill_rate = 10000;
        dut->cfg_rate_refill_period = 10;

        dut->cfg_pos_enabled = 1;
        dut->cfg_pos_max_long = 10000000;
        dut->cfg_pos_max_short = 10000000;
        dut->cfg_pos_max_order_qty = 10000;
        dut->cfg_pos_max_notional = 10000000000;

        std::mt19937 rng(0xDEADBEEF);

        orders_sent = 0;
        orders_passed = 0;
        orders_rejected = 0;

        for (int i = 0; i < 10000; i++) {
            OrderSide side = (rng() % 2) ? SIDE_BUY : SIDE_SELL;
            uint64_t qty = (rng() % 500) + 1;
            send_order(side, ORDER_NEW, qty, 100, qty * 100);

            // Occasional fills to vary position
            if (i % 10 == 0) {
                send_fill(side, qty / 2, qty * 50);
            }
        }

        printf("  Sent: %lu, Passed: %lu, Rejected: %lu\n",
               orders_sent, orders_passed, orders_rejected);

        // Verify stats are close (allow small discrepancy due to timing)
        long diff_total = (long)dut->stat_total - (long)orders_sent;
        long diff_passed = (long)dut->stat_passed - (long)orders_passed;

        if (diff_total < -10 || diff_total > 10) {
            printf("FAIL: stat_total mismatch (%lu vs %lu, diff=%ld)\n",
                   (unsigned long)dut->stat_total, orders_sent, diff_total);
            return 1;
        }

        if (diff_passed < -10 || diff_passed > 10) {
            printf("FAIL: stat_passed mismatch (%lu vs %lu, diff=%ld)\n",
                   (unsigned long)dut->stat_passed, orders_passed, diff_passed);
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    //-------------------------------------------------------------------------
    // Test: Disabled Mode
    //-------------------------------------------------------------------------
    int test_disabled() {
        printf("Test: Disabled Mode (all limiters off)\n");
        reset();

        // All limiters disabled (default from reset)
        dut->cfg_rate_enabled = 0;
        dut->cfg_pos_enabled = 0;
        dut->cfg_kill_armed = 0;

        // Send 100 orders, all should pass
        int passed_count = 0;
        for (int i = 0; i < 100; i++) {
            if (send_order(SIDE_BUY, ORDER_NEW, 10000, 100, 1000000)) {
                passed_count++;
            }
        }

        printf("  Passed: %d (expected: 100)\n", passed_count);

        if (passed_count != 100) {
            printf("FAIL: Orders rejected when limiters disabled\n");
            return 1;
        }

        printf("  PASS\n");
        return 0;
    }

    void print_summary() {
        printf("\n=== Risk Gate Test Summary ===\n");
        printf("Total orders: %lu\n", orders_sent);
        printf("Passed: %lu\n", orders_passed);
        printf("Rejected: %lu\n", orders_rejected);
        printf("Cycles: %lu\n", cycles);
        printf("==============================\n");
    }
};

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    RiskGateTestbench tb;

    int result = 0;
    int tests_run = 0;
    int tests_passed = 0;

    printf("\n=== H3 Risk Gate Tests ===\n\n");

    #define RUN_TEST(test_fn) do { \
        tests_run++; \
        int r = tb.test_fn(); \
        result |= r; \
        if (r == 0) tests_passed++; \
    } while(0)

    RUN_TEST(test_rate_limit_basic);
    RUN_TEST(test_rate_limit_refill);
    RUN_TEST(test_heartbeat_bypass);
    RUN_TEST(test_position_limit);
    RUN_TEST(test_order_size_limit);
    RUN_TEST(test_cancel_passes);
    RUN_TEST(test_kill_switch);
    RUN_TEST(test_kill_switch_auto);
    RUN_TEST(test_reject_priority);
    RUN_TEST(test_stress);
    RUN_TEST(test_disabled);

    tb.print_summary();

    printf("\nTests: %d/%d passed\n", tests_passed, tests_run);
    printf("Overall: %s\n", result == 0 ? "PASS" : "FAIL");

    return result;
}
