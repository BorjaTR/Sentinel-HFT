"use client";

import { motion } from "framer-motion";
import {
  Zap,
  Brain,
  Activity,
  Shield,
  Layers,
  GitBranch,
  BarChart3,
  Bug,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const features = [
  {
    icon: Zap,
    title: "Nanosecond Precision",
    description:
      "Hardware-timestamped traces with 64-bit nanosecond resolution. No software jitter, no approximations.",
    color: "text-yellow-400",
    bgColor: "bg-yellow-400/10",
  },
  {
    icon: Brain,
    title: "AI-Powered Analysis",
    description:
      "Claude analyzes your traces, identifies bottlenecks, and explains root causes in plain English.",
    color: "text-purple-400",
    bgColor: "bg-purple-400/10",
  },
  {
    icon: Activity,
    title: "284K Traces/sec",
    description:
      "Process millions of trace records efficiently. Real-time verification for production workloads.",
    color: "text-sentinel-400",
    bgColor: "bg-sentinel-400/10",
  },
  {
    icon: Shield,
    title: "RTL-Native Integration",
    description:
      "Drop-in SystemVerilog modules for FPGA instrumentation. Zero-overhead when disabled.",
    color: "text-blue-400",
    bgColor: "bg-blue-400/10",
  },
  {
    icon: Layers,
    title: "Latency Attribution",
    description:
      "Break down end-to-end latency by pipeline stage: ingress, core, risk checks, and egress.",
    color: "text-orange-400",
    bgColor: "bg-orange-400/10",
  },
  {
    icon: GitBranch,
    title: "CI/CD Integration",
    description:
      "GitHub Actions, GitLab CI, and Jenkins ready. Fail builds when latency budgets are exceeded.",
    color: "text-pink-400",
    bgColor: "bg-pink-400/10",
  },
  {
    icon: BarChart3,
    title: "Rich Visualizations",
    description:
      "Grafana dashboards, Prometheus metrics, and timeline views for deep performance insights.",
    color: "text-cyan-400",
    bgColor: "bg-cyan-400/10",
  },
  {
    icon: Bug,
    title: "Fault Injection",
    description:
      "Test resilience with controlled latency spikes, clock drift, and backpressure scenarios.",
    color: "text-red-400",
    bgColor: "bg-red-400/10",
  },
];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5 },
  },
};

export function Features() {
  return (
    <section id="features" className="py-24 relative">
      <div className="container mx-auto px-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-16"
        >
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            Everything You Need for{" "}
            <span className="gradient-text">HFT Latency Verification</span>
          </h2>
          <p className="text-gray-400 max-w-2xl mx-auto">
            From hardware instrumentation to AI-powered analysis, Sentinel-HFT
            provides the complete toolkit for FPGA trading system verification.
          </p>
        </motion.div>

        <motion.div
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true }}
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6"
        >
          {features.map((feature, index) => (
            <motion.div key={index} variants={itemVariants}>
              <Card className="h-full bg-dark-card/50 border-dark-border hover:border-sentinel-500/50 transition-colors group">
                <CardHeader>
                  <div
                    className={`w-12 h-12 rounded-lg ${feature.bgColor} flex items-center justify-center mb-4 group-hover:scale-110 transition-transform`}
                  >
                    <feature.icon className={feature.color} size={24} />
                  </div>
                  <CardTitle className="text-lg">{feature.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-gray-400 text-sm">{feature.description}</p>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
