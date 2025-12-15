"use client";

import { motion } from "framer-motion";
import { ArrowRight, Github, Package } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export function CTA() {
  return (
    <section className="py-24 relative overflow-hidden">
      {/* Background Effects */}
      <div className="absolute inset-0 bg-gradient-to-t from-sentinel-500/10 via-transparent to-transparent" />
      <div className="absolute bottom-0 left-1/4 w-96 h-96 bg-sentinel-500/20 rounded-full blur-3xl" />
      <div className="absolute top-0 right-1/4 w-96 h-96 bg-sentinel-600/20 rounded-full blur-3xl" />

      <div className="container mx-auto px-4 relative">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="max-w-3xl mx-auto text-center"
        >
          <h2 className="text-3xl md:text-5xl font-bold mb-6">
            Ready to Catch{" "}
            <span className="gradient-text">Nanosecond Regressions</span>?
          </h2>
          <p className="text-lg text-gray-400 mb-10 max-w-2xl mx-auto">
            Start verifying your FPGA trading system latency in minutes.
            Free, open source, and production-ready.
          </p>

          {/* Install Command */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="mb-10"
          >
            <div className="inline-flex items-center gap-4 px-6 py-4 rounded-xl bg-dark-card border border-dark-border">
              <span className="text-gray-500 font-mono">$</span>
              <code className="text-sentinel-400 font-mono">
                pip install sentinel-hft
              </code>
              <button
                onClick={() => {
                  navigator.clipboard.writeText("pip install sentinel-hft");
                }}
                className="text-gray-400 hover:text-white transition-colors"
                title="Copy to clipboard"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
                  <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
                </svg>
              </button>
            </div>
          </motion.div>

          {/* CTA Buttons */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.3 }}
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
            <Button size="lg" variant="outline" asChild>
              <a
                href="https://github.com/BorjaTR/Sentinel-HFT"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center"
              >
                <Github size={18} className="mr-2" />
                View on GitHub
              </a>
            </Button>
            <Button size="lg" variant="ghost" asChild>
              <a
                href="https://pypi.org/project/sentinel-hft/"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center"
              >
                <Package size={18} className="mr-2" />
                PyPI Package
              </a>
            </Button>
          </motion.div>

          {/* Trust Indicators */}
          <motion.div
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.5 }}
            className="mt-12 flex flex-wrap justify-center gap-8 text-gray-500 text-sm"
          >
            <div className="flex items-center gap-2">
              <svg
                className="text-sentinel-400"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="currentColor"
              >
                <path d="M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z" />
              </svg>
              <span>MIT License</span>
            </div>
            <div className="flex items-center gap-2">
              <svg
                className="text-sentinel-400"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
              <span>Production Ready</span>
            </div>
            <div className="flex items-center gap-2">
              <svg
                className="text-sentinel-400"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span>100% Test Coverage</span>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
