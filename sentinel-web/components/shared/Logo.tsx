"use client";

import { motion } from "framer-motion";
import { Activity } from "lucide-react";

interface LogoProps {
  size?: "sm" | "md" | "lg";
  showText?: boolean;
}

const sizes = {
  sm: { icon: 20, text: "text-lg" },
  md: { icon: 24, text: "text-xl" },
  lg: { icon: 32, text: "text-2xl" },
};

export function Logo({ size = "md", showText = true }: LogoProps) {
  const { icon, text } = sizes[size];

  return (
    <motion.div
      className="flex items-center gap-2"
      whileHover={{ scale: 1.02 }}
      transition={{ type: "spring", stiffness: 400, damping: 10 }}
    >
      <div className="relative">
        <div className="absolute inset-0 bg-sentinel-500/30 blur-lg rounded-full" />
        <Activity
          size={icon}
          className="relative text-sentinel-400"
          strokeWidth={2.5}
        />
      </div>
      {showText && (
        <span className={`font-bold ${text} tracking-tight`}>
          <span className="text-white">Sentinel</span>
          <span className="text-sentinel-400">-HFT</span>
        </span>
      )}
    </motion.div>
  );
}
