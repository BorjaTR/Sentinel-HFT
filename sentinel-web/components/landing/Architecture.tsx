"use client";

import { motion } from "framer-motion";
import { ArrowRight, Cpu, Database, BarChart2, Brain, Monitor } from "lucide-react";

const stages = [
  {
    icon: Cpu,
    title: "FPGA RTL",
    description: "Hardware instrumentation captures timestamps at each pipeline stage",
    color: "text-blue-400",
    bgColor: "bg-blue-400",
  },
  {
    icon: Database,
    title: "Binary Traces",
    description: "Compact v1.2 format with attribution, protocol context, and fault flags",
    color: "text-purple-400",
    bgColor: "bg-purple-400",
  },
  {
    icon: BarChart2,
    title: "Analysis Engine",
    description: "Python SDK computes percentiles, detects anomalies, and generates reports",
    color: "text-orange-400",
    bgColor: "bg-orange-400",
  },
  {
    icon: Brain,
    title: "AI Explainer",
    description: "Claude analyzes results and provides actionable optimization advice",
    color: "text-sentinel-400",
    bgColor: "bg-sentinel-400",
  },
  {
    icon: Monitor,
    title: "Observability",
    description: "Grafana dashboards, Prometheus metrics, and Slack alerts",
    color: "text-cyan-400",
    bgColor: "bg-cyan-400",
  },
];

export function Architecture() {
  return (
    <section className="py-24 relative overflow-hidden">
      <div className="container mx-auto px-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-16"
        >
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            How It Works
          </h2>
          <p className="text-gray-400 max-w-2xl mx-auto">
            From FPGA hardware to AI-powered insights in a seamless pipeline
          </p>
        </motion.div>

        {/* Desktop Architecture Flow */}
        <div className="hidden lg:block">
          <div className="relative">
            {/* Connection Line */}
            <div className="absolute top-1/2 left-0 right-0 h-0.5 bg-gradient-to-r from-blue-400 via-purple-400 to-cyan-400 opacity-20" />

            <div className="flex justify-between items-center relative">
              {stages.map((stage, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.5, delay: index * 0.1 }}
                  className="flex flex-col items-center relative z-10"
                >
                  {/* Icon */}
                  <div
                    className={`w-16 h-16 rounded-2xl ${stage.bgColor}/20 flex items-center justify-center mb-4 border border-dark-border`}
                  >
                    <stage.icon className={stage.color} size={28} />
                  </div>

                  {/* Title */}
                  <h3 className="font-semibold text-white mb-2">{stage.title}</h3>

                  {/* Description */}
                  <p className="text-gray-400 text-sm text-center max-w-[160px]">
                    {stage.description}
                  </p>

                  {/* Arrow */}
                  {index < stages.length - 1 && (
                    <ArrowRight
                      className="absolute -right-8 top-8 text-gray-600"
                      size={20}
                    />
                  )}
                </motion.div>
              ))}
            </div>
          </div>
        </div>

        {/* Mobile Architecture Flow */}
        <div className="lg:hidden">
          <div className="space-y-6">
            {stages.map((stage, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: index * 0.1 }}
                className="flex items-start gap-4"
              >
                {/* Connector */}
                <div className="flex flex-col items-center">
                  <div
                    className={`w-12 h-12 rounded-xl ${stage.bgColor}/20 flex items-center justify-center border border-dark-border shrink-0`}
                  >
                    <stage.icon className={stage.color} size={24} />
                  </div>
                  {index < stages.length - 1 && (
                    <div className="w-0.5 h-8 bg-dark-border mt-2" />
                  )}
                </div>

                {/* Content */}
                <div className="pt-2">
                  <h3 className="font-semibold text-white mb-1">{stage.title}</h3>
                  <p className="text-gray-400 text-sm">{stage.description}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Code Example */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="mt-16 grid md:grid-cols-2 gap-6"
        >
          {/* RTL Code */}
          <div className="terminal">
            <div className="flex items-center gap-2 mb-4 pb-3 border-b border-dark-border">
              <div className="w-2 h-2 rounded-full bg-sentinel-500" />
              <span className="text-gray-500 text-sm font-mono">tracer.sv</span>
            </div>
            <pre className="text-sm overflow-x-auto">
              <code>
                <span className="text-purple-400">module</span>{" "}
                <span className="text-sentinel-400">sentinel_tracer</span> (
                <br />
                {"  "}<span className="text-purple-400">input</span>{" "}
                <span className="text-blue-400">logic</span> clk,
                <br />
                {"  "}<span className="text-purple-400">input</span>{" "}
                <span className="text-blue-400">logic</span> valid,
                <br />
                {"  "}<span className="text-purple-400">input</span>{" "}
                <span className="text-blue-400">logic</span> [<span className="text-orange-400">3</span>:<span className="text-orange-400">0</span>] stage
                <br />
                );
                <br />
                <br />
                {"  "}<span className="text-gray-500">// Capture timestamp on valid</span>
                <br />
                {"  "}<span className="text-purple-400">always_ff</span> @(<span className="text-purple-400">posedge</span> clk)
                <br />
                {"    "}<span className="text-purple-400">if</span> (valid)
                <br />
                {"      "}trace_buf[wr_ptr] &lt;= {"{"}
                <br />
                {"        "}timestamp, stage, <span className="text-orange-400">1</span>&apos;b1
                <br />
                {"      "}{"}"};
                <br />
                <span className="text-purple-400">endmodule</span>
              </code>
            </pre>
          </div>

          {/* Python Code */}
          <div className="terminal">
            <div className="flex items-center gap-2 mb-4 pb-3 border-b border-dark-border">
              <div className="w-2 h-2 rounded-full bg-blue-500" />
              <span className="text-gray-500 text-sm font-mono">analyze.py</span>
            </div>
            <pre className="text-sm overflow-x-auto">
              <code>
                <span className="text-purple-400">from</span>{" "}
                <span className="text-blue-400">sentinel_hft</span>{" "}
                <span className="text-purple-400">import</span> WindTunnel
                <br />
                <br />
                <span className="text-gray-500"># Load and analyze traces</span>
                <br />
                wt = WindTunnel(<span className="text-sentinel-400">&quot;traces.bin&quot;</span>)
                <br />
                report = wt.verify(budget_ns=<span className="text-orange-400">850</span>)
                <br />
                <br />
                <span className="text-gray-500"># Get AI explanation</span>
                <br />
                <span className="text-purple-400">if</span> report.has_anomalies:
                <br />
                {"    "}explanation = wt.explain()
                <br />
                {"    "}print(explanation.summary)
                <br />
                <br />
                <span className="text-gray-500"># Export to Prometheus</span>
                <br />
                wt.export_prometheus()
              </code>
            </pre>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
