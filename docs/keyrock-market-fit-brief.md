# Sentinel-HFT → Keyrock: Market-Fit Strategy Brief

**Date:** 21 April 2026
**Author:** Borja Tarazona (research synthesis)
**Status:** Working document — positioning options, not a final pitch

---

## TL;DR

Keyrock is one of a very small set of crypto market makers that almost certainly has a production FPGA path and the budget to invest in observability. In April 2026 three things collide that make the timing unusually good: (1) their **$1.1B Series C led by SC Ventures closed 31 March 2026** — fresh capital tagged for "infrastructure," (2) **DORA** is in force and **Belgium's FSMA MiCA empowerment is still delayed** into mid-2026, putting audit-evidence burden on their stack, and (3) the **venue mix has shifted hard toward Hyperliquid / Lighter / Jito-era Solana**, where nanosecond attribution is still genuinely differentiating. Sentinel-HFT should not be pitched as a generic FPGA debugger — it should be pitched as **operational-resilience evidence for 24/7 crypto venues**, with Solana MEV and on-chain perps as the "why now" technical demo.

The honest skeptical view is also important: HFT firms don't buy observability tools that route traces through third-party LLM APIs, and they don't trust open source on the hot path. Those constraints shape where the tool fits (staging, post-trade, audit evidence) and where it doesn't (live production risk gate).

---

## 1. Why Keyrock is a legitimate ICP

**FPGA signal is real.** Archived LinkedIn postings from 2023 show Keyrock hired an **"FPGA Lead (Remote)"** in both Paris and Singapore — 5+ years FPGA experience, VHDL/Verilog, "low-latency FPGA solutions." That is rare signal. Most crypto market makers (GSR, B2C2, Flowdesk, Cumberland) show no public FPGA footprint. Keyrock does.

**Scale and funding.** 220 people, 37 countries, 85+ CEX/DEX venues, entities in Belgium / UK / Switzerland / France / US. Series C at **$1.1B valuation led by SC Ventures (Standard Chartered's venture arm)**, CoinDesk 31 March 2026. Kevin de Patoul's framing in the CoinDesk piece: 2026 is *"a transition year … crypto becoming infrastructure."* That is the language to echo.

**Tech stack confirmed.** Rust primary, plus Node/Python/C++ (Rust Foundation member spotlight). That aligns cleanly with a tool that sits alongside their own infrastructure rather than inside it.

**Regulatory posture.** Enhanced PSAN registration from the French AMF and TVTG in Liechtenstein, ahead of full MiCA. But Belgium is a complication — the FSMA was only empowered to grant MiCA licences via the Law of 11 Dec 2025, and the transitional passporting regime runs through mid-2026. A Brussels-HQ firm operating under transitional rules has an *auditability* problem, not just a tech problem.

---

## 2. The "why now" — April 2026 market hooks

Any pitch that doesn't touch at least one of these is off-trend.

**DORA in force (17 Jan 2025).** MiCA-authorised CASPs are explicitly in scope. Fines up to **2% of worldwide turnover** for financial entities, **1% of daily turnover** for critical ICT providers. Mandatory threat-led penetration testing every three years, standardised incident reporting, third-party ICT risk oversight. Splunk, Datadog and PagerDuty are all being cited in DORA implementation write-ups — meaning the "observability as audit evidence" budget line is now a real thing, not a nice-to-have. Packet capture + cycle-accurate latency attribution are directly applicable as TLPT and incident-reporting artefacts.

**Hyperliquid is no longer alone.** Hyperliquid sits at ~$4–8B/day and $208B/30d (Mar 2026), **but Lighter flipped it in 30-day volume** ($198B vs $166B). HIP-3 permissionless market creation is the structural change. The perps business has moved on-chain, and no one has mature latency observability for on-chain execution paths — block-inclusion latency, sequencer RTT, and intent-flow attribution are untracked by incumbent tools.

**Solana MEV is structured infrastructure.** Jito client holds 94% of stake; 2025 MEV revenue $720M; >3B bundles processed. **JitoBAM (encrypted mempools)** and **Harmonic (block-builder aggregation)** are the 2026 primitives. Physical constraint: 400ms slot time — a 150ms RTT often misses a slot entirely, so measuring and attributing the last 50ms is genuinely worth something.

**CME crypto derivatives record.** $12B average daily in 2025; Nov 2025 hit 424K contracts/day. **CME added Cardano, Chainlink, Stellar futures on 15 Jan 2026.** This is the market where FPGA-grade latency always paid, and the product surface keeps expanding.

**Deribit still owns options.** ~85–90% BTC options OI, $79.5B volume in Feb 2026 alone, $28.5B Boxing Day expiry. Deribit colo at Equinix LD4 is still the one crypto-native venue where wire-to-wire latency monetises directly.

**Exegy 2026 State of Trading Infrastructure** (survey of 61 senior leaders) is the single most citeable artefact: **~75% reported market-data disruption in high volatility**, **~60% named market-data processing their top investment priority**. The "infrastructure not keeping up with automation and extended hours" narrative is now industry consensus, not vendor marketing.

**Competitor activity.** Pico shipped **Corvil 12000** (Sep 2025, >2x prior perf), took over **Coinbase Derivatives infrastructure (Apr 2025)** with PicoNet+Corvil, and expanded APAC/EMEA/Americas venue coverage (Feb 2026). Exegy shipped **Nexus** Q4 2025 and won **Texas Stock Exchange core infrastructure** (Feb 2026). Both are pushing upmarket into exchange-grade telemetry — which means the observability budget is growing, *but* the incumbents are also actively defending the category.

**AMD Versal Premium Gen 2.** Dev tools Q2 2025, samples early 2026, production H2 2026. Real production HFT deployment: **late 2026 / early 2027**. Today's in-production cards (e.g. ADHOC Teknoloji HFFT-02A) are Gen 1. Don't lead with Gen 2 — too speculative — but it's the right "this is where it's going" peripheral point for an engineering conversation.

---

## 3. Three positioning options

Each of these is defensible. They imply different product postures and different buyer personas.

### Option A — "DORA-grade audit evidence for 24/7 venues"

**Frame:** Sentinel-HFT produces cycle-accurate, timestamp-correlated trace evidence that satisfies DORA TLPT and incident-reporting obligations for CASPs, while also giving the trading desk latency attribution. You're not selling observability — you're selling **audit artefacts that also happen to be useful**.

**Why this wins for Keyrock specifically:** SC Ventures is Standard Chartered-adjacent. Bank-affiliated investors push portfolio companies toward bank-grade resilience evidence within 6–12 months of an investment. Belgium FSMA transitional regime ends mid-2026 — Keyrock's audit posture needs to be buttoned up before supervision lands. Pico/Corvil are incumbent here but they are *network-layer passive* — they don't see inside the FPGA. Sentinel-HFT's risk-gate and v1.2 per-stage attribution are the gap.

**Risk:** DORA framing sells to CFO/Compliance, not to the FPGA Lead. Requires a two-audience deck. Also commoditises easily if Pico or Exegy bolt an "audit export" onto their existing products in 2026.

### Option B — "Latency attribution for Hyperliquid / Lighter / Solana MEV"

**Frame:** On-chain perps and MEV are the 2026 venue growth story. Nobody has good per-stage latency attribution for these paths (ingress from RPC / Jito relayer → core quoting → risk → egress → block-inclusion). Sentinel-HFT's streaming P99/P99.9 with O(1) memory and pipeline-stage breakdown maps directly onto this.

**Why this wins:** It's the "why now" hook that makes the demo interesting. Engineers will actually play with it. It positions Sentinel-HFT as the first observability tool built *for crypto*, not repurposed from equities.

**Risk:** Keyrock's on-chain perps exposure is real but secondary; their bread-and-butter is still CEX market making and OTC options. You may find yourself talking to the DeFi sub-team, not the main trading floor. The venues themselves aren't FPGA-friendly — this is a software/host-side story that doesn't leverage the RTL wrapper at all, which arguably undersells Sentinel-HFT's strongest technical asset.

### Option C — "In-FPGA risk gate + kill switch as a reference design"

**Frame:** Keyrock runs an options desk. Options = fast quoting with hard risk limits and kill-switch semantics. Sentinel-HFT's `risk_gate.sv` and `kill_switch.sv` are a credible open-source reference for hardware pre-trade risk controls. Pitch Sentinel-HFT as the **non-alpha** layer of their FPGA stack — the part they don't need to build themselves — with observability bundled in.

**Why this wins:** Pre-trade risk is the single FPGA use case that transfers cleanly from TradFi to crypto, is regulatorily flavoured (DORA, MiCA best-execution), and doesn't touch anyone's alpha. Also the single most defensible tier-1 use case against "we'll just build it" — because risk gates are table stakes and nobody wants to maintain them.

**Risk:** Open-source on the hot path is culturally hard to sell. Will need rigorous proof of zero critical-path overhead and trust-building around the RTL. AI explanations have to be opt-in and offline-capable — no Anthropic API calls on production traces.

---

## 4. The honest skeptical view

A disciplined HFT firm has real reasons not to adopt Sentinel-HFT as shipped:

- **LLM API = data exfiltration risk.** Routing traces through Claude's API is a compliance non-starter at most prop desks. This needs a local/on-prem inference mode to be viable. Without it, Option A (DORA) is contradictory — you can't claim audit evidence while leaking to a third party.
- **Python in the critical path = automatic no.** The streaming analyzer is fine for post-trade and dashboards. It will not be allowed anywhere near live quoting. Be explicit about that boundary in the pitch; don't let it be discovered later.
- **HdrHistogram vs P² quantile estimation.** HdrHistogram (Gil Tene) is the HFT industry standard because it preserves the whole distribution — tail behaviour is where the bodies are buried. P² is elegant and O(1), but a rigorous buyer will ask why not HdrHistogram. Have the answer ready: P² for always-on streaming at the RTL boundary, HdrHistogram for batch/post-trade — both, not either.
- **ChipScope / SignalTap is already there.** Xilinx ILA has a 20-year mindshare lead for FPGA debug. Your wedge is *always-on, production-grade, non-invasive, with streaming export* — not a better debugger. Be precise.
- **Fault injection in production is politically radioactive.** Frame it as staging/regression only. Calling it "chaos for trading systems" will lose the room.
- **NIH and secrecy are real.** The core alpha engine is sacred. Sentinel-HFT's TAM is the observability and risk-gate perimeter, not the core. Don't pitch it otherwise.
- **TAM is dozens of shops, not hundreds.** Be honest with yourself about this. The realistic crypto FPGA universe is roughly: Jump Crypto, Flow Traders digital, HRT crypto desk, Wintermute (soft), Keyrock, and the long tail of sub-$500M prop shops. That's fine for open-source with consulting upside — it's not a VC-scale SaaS business as currently packaged.

---

## 5. Recommended path — "latest of the latest" version

Lead with **Option A (DORA-grade audit evidence)** as the top-line hook, **use Option B (Solana / Hyperliquid latency attribution) as the technical demo**, and keep **Option C (risk gate / kill switch reference design)** as the fallback expansion story once they know you.

Concretely, for a Keyrock outreach cycle:

1. Write a 2-pager titled something like *"Audit-ready latency attribution for crypto market makers: a DORA-compatible open-source starter kit."* Cite the Exegy 2026 report, the CoinDesk Series C piece, and DORA Article 18 (incident reporting).
2. Build a **Hyperliquid / Lighter / Jito block-inclusion latency demo** on Sentinel-HFT's v1.2 trace format — pipeline stage breakdown ingress → core → risk → egress, plus block-inclusion delta. This is the demo that gets an FPGA Lead to open the repo.
3. Offer **local-only AI explanations** (Ollama, local Llama-class model) as a config option before any Keyrock conversation. This kills the single biggest objection.
4. Route the intro through **Brussels engineering leadership** (not commercial), and anchor the conversation on DORA + the Belgian FSMA transitional regime — which they're dealing with anyway.
5. Prepare the **HdrHistogram vs P² answer** and the **zero-overhead proof** (post a STAC-style micro-benchmark) before the first engineer meeting. Both questions will be asked.

---

## Key sources

- *Crypto investment firm Keyrock valued at $1.1 billion in Series C led by SC Ventures* — CoinDesk, 31 Mar 2026
- *Keyrock Secures Series C Funding From SC Ventures* — Keyrock
- *Implementing MiCA in Belgium* — DLA Piper, Oct 2025
- Keyrock LinkedIn — *FPGA Lead (Remote)* postings, Paris + Singapore, 2023
- *CME Group's average crypto derivatives volume hit record $12 billion in 2025* — CoinDesk
- *CME to Expand Crypto Derivatives Suite (Cardano, Chainlink, Stellar)* — CME, 15 Jan 2026
- *Deribit's $28.5B Boxing Day Options Expiry* — Bitcoin.com News
- *Hyperliquid TVL, Fees, Revenue & Volume* — DefiLlama
- *Lighter flips Hyperliquid in 30-day perps volume* — Bitget News
- *Jito Labs and the Future of Solana's MEV Infrastructure* — AInvest
- *Pico Establishes Relationship with Coinbase Derivatives* — Pico, Apr 2025
- *Pico builds out market coverage APAC/EMEA/Americas* — The TRADE, Feb 2026
- *Exegy 2026 State of Trading Infrastructure*
- *DORA, Operational Resilience and Intelligent Observability* — Splunk
- *How DORA will affect the digital asset space* — Fireblocks
- *AMD Versal Premium Gen 2* — AMD IR
- *ADHOC Teknoloji HFFT-02A Versal Premium STAC-T1* — STAC Research
