"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";

const demoLines = [
  { text: "$ sentinel-hft verify traces.bin --budget 850ns", delay: 0, type: "input" },
  { text: "", delay: 500, type: "empty" },
  { text: "Loading trace file... 1,247,832 records", delay: 800, type: "info" },
  { text: "Computing latency statistics...", delay: 1200, type: "info" },
  { text: "", delay: 1400, type: "empty" },
  { text: "┌─────────────────────────────────────────────────────────────┐", delay: 1600, type: "box" },
  { text: "│  LATENCY VERIFICATION REPORT                                │", delay: 1650, type: "box" },
  { text: "├─────────────────────────────────────────────────────────────┤", delay: 1700, type: "box" },
  { text: "│  Metric          │ Value      │ Budget     │ Status        │", delay: 1750, type: "box" },
  { text: "├─────────────────────────────────────────────────────────────┤", delay: 1800, type: "box" },
  { text: "│  P50             │ 423ns      │ -          │ -             │", delay: 1850, type: "box" },
  { text: "│  P90             │ 712ns      │ -          │ -             │", delay: 1900, type: "box" },
  { text: "│  P99             │ 847ns      │ 850ns      │ ✓ PASS        │", delay: 1950, type: "pass" },
  { text: "│  P99.9           │ 923ns      │ -          │ -             │", delay: 2000, type: "box" },
  { text: "│  Max             │ 1,247ns    │ -          │ -             │", delay: 2050, type: "box" },
  { text: "├─────────────────────────────────────────────────────────────┤", delay: 2100, type: "box" },
  { text: "│  Throughput      │ 284,535 records/sec                      │", delay: 2150, type: "box" },
  { text: "│  Total Records   │ 1,247,832                                │", delay: 2200, type: "box" },
  { text: "└─────────────────────────────────────────────────────────────┘", delay: 2250, type: "box" },
  { text: "", delay: 2400, type: "empty" },
  { text: "Attribution breakdown:", delay: 2500, type: "info" },
  { text: "  ├── core:    52% (443ns avg)", delay: 2600, type: "attr" },
  { text: "  ├── risk:    31% (264ns avg)", delay: 2700, type: "attr" },
  { text: "  ├── ingress:  9% (77ns avg)", delay: 2800, type: "attr" },
  { text: "  └── egress:   8% (68ns avg)", delay: 2900, type: "attr" },
  { text: "", delay: 3100, type: "empty" },
  { text: "✓ Verification complete - all budgets met", delay: 3200, type: "success" },
];

export function TerminalDemo() {
  const [visibleLines, setVisibleLines] = useState<number>(0);
  const [isTyping, setIsTyping] = useState(false);

  useEffect(() => {
    const startDemo = () => {
      setVisibleLines(0);
      setIsTyping(true);

      demoLines.forEach((line, index) => {
        setTimeout(() => {
          setVisibleLines(index + 1);
          if (index === demoLines.length - 1) {
            setIsTyping(false);
          }
        }, line.delay);
      });
    };

    startDemo();

    // Loop the demo
    const interval = setInterval(() => {
      startDemo();
    }, 8000);

    return () => clearInterval(interval);
  }, []);

  const getLineColor = (type: string) => {
    switch (type) {
      case "input":
        return "text-sentinel-400";
      case "info":
        return "text-gray-400";
      case "pass":
        return "text-green-400";
      case "success":
        return "text-green-400";
      case "attr":
        return "text-blue-400";
      case "box":
        return "text-gray-500";
      default:
        return "text-gray-400";
    }
  };

  return (
    <section className="py-24 relative overflow-hidden">
      <div className="container mx-auto px-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-12"
        >
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            See It In Action
          </h2>
          <p className="text-gray-400 max-w-2xl mx-auto">
            Watch Sentinel-HFT analyze over a million trace records in real-time,
            computing precise latency percentiles with nanosecond accuracy.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 40 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="max-w-4xl mx-auto"
        >
          <div className="terminal overflow-hidden">
            {/* Terminal Header */}
            <div className="flex items-center gap-2 mb-4 pb-4 border-b border-dark-border">
              <div className="w-3 h-3 rounded-full bg-red-500" />
              <div className="w-3 h-3 rounded-full bg-yellow-500" />
              <div className="w-3 h-3 rounded-full bg-green-500" />
              <span className="ml-4 text-gray-500 text-sm font-mono">
                sentinel-hft verification
              </span>
              {isTyping && (
                <span className="ml-auto text-sentinel-400 text-sm animate-pulse">
                  running...
                </span>
              )}
            </div>

            {/* Terminal Content */}
            <div className="font-mono text-sm space-y-1 min-h-[500px]">
              {demoLines.slice(0, visibleLines).map((line, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.1 }}
                  className={getLineColor(line.type)}
                >
                  {line.text || "\u00A0"}
                </motion.div>
              ))}
              {isTyping && visibleLines < demoLines.length && (
                <span className="inline-block w-2 h-4 bg-sentinel-400 animate-blink" />
              )}
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
