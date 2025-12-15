export interface DemoResponse {
  triggers: string[];
  response: string;
}

export const DEMO_RESPONSES: DemoResponse[] = [
  {
    triggers: ["demo", "sample", "example", "try", "start", "analyze"],
    response: `Here's the analysis of the demo trace file:

**Status: Healthy**

The system is performing well overall. Your P99 latency is **89ns**, which is within normal operating range for a well-tuned FPGA trading system.

**Key Findings:**

1. **Bottleneck identified: Core stage (52%)**
   - The core trading logic consumes over half of total latency at 45ns
   - This is typical for systems with complex order matching logic
   - Consider pipelining or caching frequently-accessed data structures

2. **Two anomalies detected:**
   - **Latency spike at t=2.341s** (3.2x baseline) - likely caused by a cache miss or complex order type
   - **Brief backpressure at t=3.892s** (47 cycles) - downstream consumer was temporarily slow

**Latency Attribution:**
| Stage | Time | % of Total |
|-------|------|------------|
| Ingress | 8ns | 9% |
| Core | 45ns | 52% |
| Risk | 27ns | 31% |
| Egress | 7ns | 8% |

Would you like me to dive deeper into any of these findings?`
  },
  {
    triggers: ["bottleneck", "slow", "why", "core"],
    response: `**Bottleneck Analysis: Core Stage**

The core stage is consuming **52% of total latency** (45ns out of 87ns). Here's what's likely happening:

**Probable Causes:**

1. **Order Book Lookup** (~20ns estimated)
   - Hash table or tree traversal for price level lookup
   - Consider: pre-computed price level indices

2. **Matching Logic** (~15ns estimated)
   - Order type validation and matching rules
   - Consider: specialized fast-path for common order types

3. **State Updates** (~10ns estimated)
   - Position tracking, fill accumulation
   - Consider: batch updates where possible

**Recommendations:**

1. **Pipeline the matching engine** - Split into 2-3 stages to increase throughput
2. **Add L1 cache for hot symbols** - Top 10 symbols likely represent 80% of volume
3. **Profile individual operations** - Use cycle-accurate counters per sub-operation

The risk stage (27ns, 31%) is also significant. If you optimize core, risk becomes your next bottleneck.

Want me to analyze the risk stage next?`
  },
  {
    triggers: ["spike", "anomaly", "2.341", "latency spike"],
    response: `**Anomaly Analysis: Latency Spike at t=2.341s**

The spike reached **285ns** (3.2x the baseline 89ns). Here's my analysis:

**Characteristics:**
- Duration: Single transaction (not sustained)
- Recovery: Immediate return to baseline
- Impact: No drops, no downstream effects

**Likely Causes (ranked by probability):**

1. **Cache Miss (80% likely)**
   - A rarely-traded symbol caused L1/L2 cache miss
   - Evidence: Isolated spike, instant recovery
   - Fix: Prefetch or pin hot data structures

2. **Complex Order Type (15% likely)**
   - Iceberg, pegged, or conditional order requiring extra logic
   - Evidence: Would explain single-transaction spike

3. **Memory Allocation (5% likely)**
   - Dynamic allocation in critical path
   - Evidence: Unlikely given your architecture

**This is not concerning** for overall system health. A 3.2x spike on a single transaction is within acceptable bounds for HFT systems.

However, if you're targeting ultra-low-latency:
- Add monitoring for cache miss rates
- Consider symbol-based sharding for hot/cold paths

Should I analyze the backpressure event as well?`
  },
  {
    triggers: ["backpressure", "3.892", "downstream"],
    response: `**Anomaly Analysis: Backpressure at t=3.892s**

**Event Details:**
- Duration: 47 cycles (470ns at 100MHz)
- P99 during event: 156ns (1.75x baseline)
- Transactions affected: ~3,000 buffered

**What Happened:**

The downstream consumer (likely your network TX or risk gateway) signaled "not ready" for 47 cycles. Your system handled this correctly:

- Trace FIFO buffered incoming transactions
- No drops occurred (FIFO didn't overflow)
- Latency increased gracefully
- Full recovery within ~100 cycles

**Root Cause Hypotheses:**

1. **Network TX buffer full** - Burst of outgoing messages
2. **Risk gateway processing spike** - Complex position calculation
3. **Downstream system GC pause** - If downstream is software-based

**Your System Did Well:**
- FIFO depth was sufficient (no drops)
- Backpressure propagation worked correctly
- Recovery was fast

**Recommendations:**
- Monitor downstream system health
- Consider alerting if backpressure exceeds 100 cycles
- Current FIFO depth appears adequate

This is a **healthy response** to a transient downstream issue. No action required unless frequency increases.`
  },
  {
    triggers: ["risk", "position", "limit"],
    response: `**Risk Stage Analysis**

The risk stage consumes **27ns (31% of total latency)**. Here's the breakdown:

**What's Happening in 27ns:**

1. **Rate Limiting Check** (~8ns)
   - Token bucket lookup and decrement
   - Very fast, well-optimized

2. **Position Limit Check** (~12ns)
   - Per-symbol position lookup
   - Long/short limit comparison
   - Notional value calculation

3. **Kill Switch Check** (~3ns)
   - Global flag check
   - Nearly zero cost when not triggered

4. **Response Assembly** (~4ns)
   - Pass/reject decision encoding
   - Rejection reason if applicable

**Optimization Opportunities:**

1. **Parallelize position lookups** - If checking multiple symbols
2. **Cache recent decisions** - Same symbol/side may repeat
3. **Simplify notional calculation** - Pre-compute at order entry

**Current Assessment:**
27ns for comprehensive risk checks is **excellent**. Most software-based risk systems are 1-10us. Your hardware implementation is ~50x faster.

The risk stage will become your bottleneck if you optimize core below 27ns. Plan accordingly.`
  },
  {
    triggers: ["throughput", "performance", "fast", "speed"],
    response: `**Performance Summary**

**Throughput: 284,535 traces/sec**

This is solid performance. Here's context:

| Metric | Your System | Typical HFT | Assessment |
|--------|-------------|-------------|------------|
| Throughput | 284K/s | 100K-500K/s | Good |
| P50 Latency | 42ns | 50-200ns | Excellent |
| P99 Latency | 89ns | 100-500ns | Excellent |
| Drop Rate | 0.0002% | <0.01% | Excellent |

**What's Limiting Throughput:**

At 284K traces/sec with 87ns average latency, you're achieving:
- ~87% pipeline utilization
- ~13% overhead (backpressure, gaps)

**To Push Higher:**

1. **Increase pipeline depth** - More transactions in flight
2. **Reduce core stage latency** - Currently the bottleneck
3. **Optimize FIFO management** - Reduce trace overhead

**Realistic Ceiling:**
With your current architecture, 350-400K/sec is achievable with optimization. Beyond that requires architectural changes (multiple cores, wider datapaths).

Your system is performing well. Focus on latency consistency rather than raw throughput.`
  },
  {
    triggers: ["help", "what can you", "how do i", "commands"],
    response: `**What I Can Help With**

I'm analyzing your trace data from Sentinel-HFT. Here's what you can ask:

**Analysis Questions:**
- "What's causing the latency spikes?"
- "Where's my bottleneck?"
- "Explain the backpressure event"
- "How's my throughput?"

**Stage-Specific:**
- "Analyze the core stage"
- "Why is risk taking 27ns?"
- "Break down the latency attribution"

**Anomalies:**
- "What happened at t=2.341s?"
- "Are these anomalies concerning?"
- "How can I prevent spikes?"

**Optimization:**
- "How do I reduce P99?"
- "What should I optimize first?"
- "Is my FIFO depth sufficient?"

**In Demo Mode:**
You're viewing a pre-analyzed sample trace. To analyze your own data, upgrade to Pro.

What would you like to know about this trace?`
  },
  {
    triggers: ["upload", "my data", "own file", "custom"],
    response: `**Upload Your Own Traces**

This feature is available in **Sentinel-HFT Pro**.

**What You Get with Pro (EUR10/month):**
- Upload your own .bin trace files
- Live AI analysis with Claude
- Custom questions about your data
- Export reports (JSON, Markdown, PDF)
- API access for CI/CD integration
- Priority support

**Free Demo Includes:**
- Full visualization of sample traces
- Interactive fault injection
- Pre-computed analysis explanations
- All UI features

[Upgrade to Pro](/pricing)

Want to continue exploring the demo data? Ask me anything about the sample trace!`
  },
  {
    triggers: ["attribution", "breakdown", "stages"],
    response: `**Latency Attribution Breakdown**

Your v1.2 trace format captures per-stage timing. Here's the full breakdown:

**Stage-by-Stage Analysis:**

| Stage | P99 Latency | % of Total | Status |
|-------|-------------|------------|--------|
| Ingress | 8ns | 9% | Optimal |
| Core | 45ns | 52% | **Bottleneck** |
| Risk | 27ns | 31% | Good |
| Egress | 7ns | 8% | Optimal |
| Overhead | 0ns | 0% | Excellent |

**Interpretation:**

1. **Ingress (8ns)** - Packet parsing and validation
   - Very efficient, no optimization needed

2. **Core (45ns)** - Order matching and execution
   - Primary bottleneck consuming 52% of latency
   - Target for optimization

3. **Risk (27ns)** - Pre-trade risk checks
   - Second largest contributor
   - Will become bottleneck after core optimization

4. **Egress (7ns)** - Response serialization
   - Well-optimized, matches ingress

5. **Overhead (0ns)** - Inter-stage queueing
   - Excellent pipeline efficiency
   - No measurable queueing delays

**Key Insight:** Your pipeline is well-balanced except for core. Optimizing core from 45ns to 25ns would reduce total latency by 23%.`
  },
  {
    triggers: ["p99", "latency", "percentile"],
    response: `**Latency Percentile Analysis**

**Current P99: 89ns**

| Percentile | Value | Interpretation |
|------------|-------|----------------|
| P50 | 42ns | Typical transaction |
| P90 | 67ns | Normal variance |
| P99 | 89ns | Tail latency |
| P99.9 | 142ns | Rare outliers |
| Max | 312ns | Single worst case |

**P99 Breakdown:**
- Your P99 (89ns) is only 2.1x your P50 (42ns)
- This is a **tight distribution** - good sign
- Most HFT systems see 3-5x P50-to-P99 ratio

**What's Contributing to P99:**
1. Complex order types (occasional)
2. Cache misses on rare symbols
3. Risk check edge cases

**How to Reduce P99:**
1. Profile P99 transactions specifically
2. Add fast-path for common cases
3. Warm caches for likely symbols
4. Pre-compute risk calculations

**Target:** A well-tuned FPGA system should achieve P99 < 100ns. You're meeting this target.`
  }
];

export function findDemoResponse(query: string): string {
  const lowerQuery = query.toLowerCase();

  for (const item of DEMO_RESPONSES) {
    for (const trigger of item.triggers) {
      if (lowerQuery.includes(trigger.toLowerCase())) {
        return item.response;
      }
    }
  }

  return `I can help you understand this trace analysis! Here are some things you can ask:

- "What's the bottleneck?"
- "Explain the latency spike"
- "How's the throughput?"
- "Analyze the risk stage"
- "Show me the attribution breakdown"

Or type **"demo"** to see a full analysis walkthrough.

*Note: You're in demo mode with pre-analyzed sample data. Upgrade to Pro to analyze your own traces.*`;
}

import { AnalysisResult } from "@/types";

export function getDemoAnalysisResult(budget: number): AnalysisResult {
  return {
    id: "demo-analysis-001",
    timestamp: new Date(),
    traceFile: "demo-traces.bin",
    totalRecords: 1247832,
    budget: budget,
    budgetMet: 847 <= budget,
    metrics: {
      p50: 423,
      p90: 712,
      p99: 847,
      p99_9: 923,
      max: 1247,
      min: 89,
      mean: 456,
      stdDev: 124,
      throughput: 284535,
    },
    attribution: {
      ingress: 9,
      core: 52,
      risk: 31,
      egress: 8,
    },
    anomalies: [
      {
        type: "latency_spike",
        severity: "medium",
        timestamp: 2.341,
        description:
          "Single transaction spike to 285ns (3.2x baseline). Likely caused by L1 cache miss on rarely-traded symbol.",
        affectedStage: "core",
      },
      {
        type: "backpressure",
        severity: "low",
        timestamp: 3.892,
        description:
          "Brief 47-cycle backpressure event. Downstream consumer temporarily busy. No drops occurred.",
        affectedStage: "egress",
      },
    ],
  };
}
