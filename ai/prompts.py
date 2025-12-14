"""Prompt templates for AI explainer."""

SYSTEM_PROMPT = """You are an expert FPGA trading systems analyst. Your job is to explain
latency analysis results in clear, actionable language.

You have deep knowledge of:
- Hardware latency characteristics (cycles, nanoseconds, jitter)
- Trading system risk controls (rate limiters, position limits, kill switches)
- Token bucket algorithms and their behavior
- Pipeline backpressure and its effects
- Common causes of latency anomalies

When explaining results:
1. Start with the most important finding
2. Explain root causes, not just symptoms
3. Provide specific, actionable recommendations
4. Use precise numbers from the data
5. Be concise - executives will read this

You will receive structured facts about a trace analysis. Your job is to synthesize
them into a coherent explanation."""


EXPLANATION_PROMPT = """Analyze this FPGA trading system trace data and provide a clear explanation.

{facts}

CONFIGURATION:
- Clock period: {clock_period_ns}ns
- Rate limiter: max_tokens={rate_max_tokens}, refill_rate={rate_refill_rate}/period
- Position limits: long={pos_max_long}, short={pos_max_short}

Please provide:
1. SUMMARY (2-3 sentences on overall system health)
2. KEY FINDINGS (bullet points of important observations)
3. ROOT CAUSE ANALYSIS (if anomalies detected)
4. RECOMMENDATIONS (specific configuration or design changes)

Keep the response under 500 words. Use technical terms appropriately."""


EXECUTIVE_SUMMARY_PROMPT = """Create a brief executive summary of this trace analysis.

{facts}

The audience is a risk manager who needs to know:
1. Is the system healthy? (yes/no with confidence)
2. Were there any concerning events?
3. Are risk controls working properly?
4. Any action items?

Keep it under 150 words. No technical jargon."""


COMPARISON_PROMPT = """Compare these two trace analysis runs:

BASELINE:
{baseline_facts}

CANDIDATE:
{candidate_facts}

Identify:
1. What improved?
2. What regressed?
3. New patterns that appeared?
4. Overall recommendation (use baseline or candidate?)

Be specific with numbers."""


# Protocol-aware prompts (H5)

PROTOCOL_CONTEXT_PROMPT = """
PROTOCOL CONTEXT:
{protocol_summary}

Financial Health:
- Treasury: ${treasury_usd:,.0f}
- Runway: {runway_months:.1f} months
- Burn Rate: ${burn_rate:,.0f}/month

Governance:
- Active Proposals: {active_proposals}
- Participation: {participation:.1%}
- Risk Flags: {risk_flags}

Recent Events:
{recent_events}
"""

PROTOCOL_AWARE_EXPLANATION_PROMPT = """Analyze this FPGA trading system trace data WITH protocol context.

{facts}

{protocol_context}

CONFIGURATION:
- Clock period: {clock_period_ns}ns
- Rate limiter: max_tokens={rate_max_tokens}, refill_rate={rate_refill_rate}/period
- Position limits: long={pos_max_long}, short={pos_max_short}

Please provide:
1. SUMMARY (2-3 sentences on system + protocol health)
2. KEY FINDINGS (bullet points including any protocol correlations)
3. ROOT CAUSE ANALYSIS (consider protocol events as potential factors)
4. RECOMMENDATIONS (include protocol-aware trading recommendations)

Keep the response under 600 words. Consider how protocol health affects trading risk."""


RISK_ASSESSMENT_PROMPT = """Provide a risk assessment for trading on this protocol.

HFT SYSTEM STATUS:
{hft_summary}

PROTOCOL STATUS:
{protocol_summary}

CORRELATIONS:
{correlations}

Questions to answer:
1. Is it safe to trade on this protocol right now?
2. What are the key risks?
3. What risk limits would you recommend?
4. Any immediate actions needed?

Be specific and actionable. This goes to a risk manager."""

