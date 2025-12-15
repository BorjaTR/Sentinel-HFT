"use client";

import { motion } from "framer-motion";
import { ArrowRight, Play, Zap, Shield, Activity } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

const features = [
  { icon: Zap, text: "284K traces/sec" },
  { icon: Shield, text: "Nanosecond precision" },
  { icon: Activity, text: "AI-powered analysis" },
];

export function Hero() {
  return (
    <section className="relative min-h-screen flex items-center justify-center overflow-hidden pt-16">
      {/* Background Effects */}
      <div className="absolute inset-0 bg-gradient-to-b from-sentinel-500/5 via-transparent to-transparent" />
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-sentinel-500/10 rounded-full blur-3xl" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-sentinel-600/10 rounded-full blur-3xl" />

      {/* Grid Pattern */}
      <div
        className="absolute inset-0 opacity-20"
        style={{
          backgroundImage: `linear-gradient(to right, rgba(34, 197, 94, 0.1) 1px, transparent 1px),
                           linear-gradient(to bottom, rgba(34, 197, 94, 0.1) 1px, transparent 1px)`,
          backgroundSize: "64px 64px",
        }}
      />

      <div className="container mx-auto px-4 relative z-10">
        <div className="max-w-4xl mx-auto text-center">
          {/* Badge */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-sentinel-500/10 border border-sentinel-500/20 mb-8"
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sentinel-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-sentinel-500" />
            </span>
            <span className="text-sentinel-400 text-sm font-medium">
              v2.2 now available with AI analysis
            </span>
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="text-4xl md:text-6xl lg:text-7xl font-bold tracking-tight mb-6"
          >
            <span className="text-white">FPGA-Grade</span>
            <br />
            <span className="gradient-text">Latency Verification</span>
          </motion.h1>

          {/* Subheadline */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-lg md:text-xl text-gray-400 max-w-2xl mx-auto mb-8"
          >
            Catch nanosecond regressions before they cost real money.
            Hardware-level tracing with AI-powered root cause analysis.
          </motion.p>

          {/* Feature Pills */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="flex flex-wrap justify-center gap-4 mb-10"
          >
            {features.map((feature, index) => (
              <div
                key={index}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-dark-card/50 border border-dark-border"
              >
                <feature.icon size={16} className="text-sentinel-400" />
                <span className="text-gray-300 text-sm">{feature.text}</span>
              </div>
            ))}
          </motion.div>

          {/* CTAs */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.4 }}
            className="flex flex-col sm:flex-row gap-4 justify-center"
          >
            <Button size="lg" asChild className="group">
              <Link href="/analyze">
                Try AI Analysis
                <ArrowRight
                  size={18}
                  className="ml-2 group-hover:translate-x-1 transition-transform"
                />
              </Link>
            </Button>
            <Button size="lg" variant="outline" asChild className="group">
              <Link href="/demo">
                <Play size={18} className="mr-2" />
                Watch Live Demo
              </Link>
            </Button>
          </motion.div>

          {/* Code Snippet Preview */}
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.6 }}
            className="mt-16 relative"
          >
            <div className="absolute inset-0 bg-gradient-to-t from-dark-bg via-transparent to-transparent z-10 pointer-events-none" />
            <div className="terminal max-w-2xl mx-auto text-left">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-3 h-3 rounded-full bg-red-500" />
                <div className="w-3 h-3 rounded-full bg-yellow-500" />
                <div className="w-3 h-3 rounded-full bg-green-500" />
                <span className="ml-4 text-gray-500 text-sm">terminal</span>
              </div>
              <code className="text-sm">
                <span className="text-gray-500">$</span>{" "}
                <span className="text-sentinel-400">pip install</span>{" "}
                <span className="text-white">sentinel-hft</span>
                <br />
                <br />
                <span className="text-gray-500">$</span>{" "}
                <span className="text-sentinel-400">sentinel-hft</span>{" "}
                <span className="text-white">verify traces.bin --budget 850ns</span>
                <br />
                <br />
                <span className="text-gray-400">
                  {"┌──────────────────────────────────────────────────┐"}
                </span>
                <br />
                <span className="text-gray-400">{"│ "}</span>
                <span className="text-sentinel-400">P99</span>
                <span className="text-white">: 847ns </span>
                <span className="text-green-400">✓ PASS</span>
                <span className="text-gray-400">{" (budget: 850ns)      │"}</span>
                <br />
                <span className="text-gray-400">{"│ "}</span>
                <span className="text-sentinel-400">Records</span>
                <span className="text-white">: 1,247,832 </span>
                <span className="text-gray-400">{"@ 284K/sec            │"}</span>
                <br />
                <span className="text-gray-400">
                  {"└──────────────────────────────────────────────────┘"}
                </span>
              </code>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
