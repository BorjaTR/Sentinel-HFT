"use client";

import { motion } from "framer-motion";
import { useEffect, useState } from "react";

const stats = [
  {
    value: 284535,
    suffix: "",
    label: "Traces/sec",
    format: (n: number) => n.toLocaleString(),
  },
  {
    value: 99.9,
    suffix: "%",
    label: "Quantile Accuracy",
    format: (n: number) => n.toFixed(1),
  },
  {
    value: 64,
    suffix: "-bit",
    label: "Timestamp Resolution",
    format: (n: number) => n.toString(),
  },
  {
    value: 12,
    suffix: "+",
    label: "Pipeline Stages",
    format: (n: number) => n.toString(),
  },
];

function AnimatedCounter({
  value,
  suffix,
  format,
  duration = 2,
}: {
  value: number;
  suffix: string;
  format: (n: number) => string;
  duration?: number;
}) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let startTime: number;
    let animationFrame: number;

    const animate = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / (duration * 1000), 1);

      // Easing function for smooth animation
      const easeOutQuart = 1 - Math.pow(1 - progress, 4);
      setCount(Math.floor(easeOutQuart * value));

      if (progress < 1) {
        animationFrame = requestAnimationFrame(animate);
      }
    };

    animationFrame = requestAnimationFrame(animate);

    return () => cancelAnimationFrame(animationFrame);
  }, [value, duration]);

  return (
    <span>
      {format(count)}
      {suffix}
    </span>
  );
}

export function Stats() {
  const [isInView, setIsInView] = useState(false);

  return (
    <section className="py-24 relative overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0 bg-gradient-to-b from-sentinel-500/5 via-transparent to-transparent" />

      <div className="container mx-auto px-4 relative">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          onViewportEnter={() => setIsInView(true)}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center mb-16"
        >
          <h2 className="text-3xl md:text-4xl font-bold mb-4">
            Built for <span className="gradient-text">Performance</span>
          </h2>
          <p className="text-gray-400 max-w-2xl mx-auto">
            Every component is optimized for high-throughput, low-latency
            verification of FPGA trading systems.
          </p>
        </motion.div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {stats.map((stat, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: index * 0.1 }}
              className="text-center"
            >
              <div className="metric-card p-8 rounded-2xl">
                <div className="text-4xl md:text-5xl font-bold text-white mb-2">
                  {isInView ? (
                    <AnimatedCounter
                      value={stat.value}
                      suffix={stat.suffix}
                      format={stat.format}
                    />
                  ) : (
                    "0"
                  )}
                </div>
                <div className="text-gray-400 text-sm">{stat.label}</div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
