"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertCircle,
  AlertTriangle,
  Info,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Target,
  Zap,
  Code,
  TrendingDown,
} from "lucide-react";
import { Prescription } from "@/types";
import { cn } from "@/lib/utils";

interface PrescriptionCardProps {
  prescription: Prescription;
  index: number;
}

const severityConfig = {
  critical: {
    icon: AlertCircle,
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
    textColor: "text-red-400",
    badgeColor: "bg-red-500/20 text-red-400",
  },
  warning: {
    icon: AlertTriangle,
    bgColor: "bg-yellow-500/10",
    borderColor: "border-yellow-500/30",
    textColor: "text-yellow-400",
    badgeColor: "bg-yellow-500/20 text-yellow-400",
  },
  info: {
    icon: Info,
    bgColor: "bg-blue-500/10",
    borderColor: "border-blue-500/30",
    textColor: "text-blue-400",
    badgeColor: "bg-blue-500/20 text-blue-400",
  },
  success: {
    icon: CheckCircle,
    bgColor: "bg-green-500/10",
    borderColor: "border-green-500/30",
    textColor: "text-green-400",
    badgeColor: "bg-green-500/20 text-green-400",
  },
};

const categoryLabels: Record<string, string> = {
  bottleneck: "Bottleneck",
  anomaly: "Anomaly",
  optimization: "Optimization",
  configuration: "Configuration",
  health: "Health",
};

const effortLabels: Record<string, { text: string; color: string }> = {
  low: { text: "Low Effort", color: "text-green-400" },
  medium: { text: "Medium Effort", color: "text-yellow-400" },
  high: { text: "High Effort", color: "text-red-400" },
};

export function PrescriptionCard({ prescription, index }: PrescriptionCardProps) {
  const [expanded, setExpanded] = useState(false);
  const config = severityConfig[prescription.severity];
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.1 }}
      className={cn(
        "rounded-lg border p-4",
        config.bgColor,
        config.borderColor
      )}
    >
      {/* Header */}
      <div
        className="flex items-start gap-3 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className={cn("p-2 rounded-lg", config.bgColor)}>
          <Icon className={cn("w-5 h-5", config.textColor)} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-white">{prescription.title}</h3>
            <span
              className={cn(
                "px-2 py-0.5 rounded-full text-xs font-medium",
                config.badgeColor
              )}
            >
              {prescription.severity.toUpperCase()}
            </span>
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-dark-border text-gray-400">
              {categoryLabels[prescription.category]}
            </span>
          </div>

          <p className="text-sm text-gray-400 mt-1 line-clamp-2">
            {prescription.diagnosis}
          </p>

          {/* Quick metrics */}
          {prescription.metrics && (
            <div className="flex items-center gap-4 mt-2 text-xs">
              <span className="flex items-center gap-1 text-gray-500">
                <TrendingDown size={12} />
                Current: {prescription.metrics.current.toLocaleString()}
                {prescription.metrics.unit}
              </span>
              <span className="flex items-center gap-1 text-sentinel-400">
                <Target size={12} />
                Target: {prescription.metrics.target.toLocaleString()}
                {prescription.metrics.unit}
              </span>
            </div>
          )}
        </div>

        <button className="p-1 hover:bg-dark-border rounded transition-colors">
          {expanded ? (
            <ChevronUp size={18} className="text-gray-400" />
          ) : (
            <ChevronDown size={18} className="text-gray-400" />
          )}
        </button>
      </div>

      {/* Expanded content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-4 pt-4 border-t border-dark-border space-y-4">
              {/* Prescription */}
              <div>
                <h4 className="flex items-center gap-2 text-sm font-medium text-white mb-2">
                  <Zap size={14} className="text-sentinel-400" />
                  Prescription
                </h4>
                <div className="text-sm text-gray-300 whitespace-pre-line bg-dark-card p-3 rounded-lg">
                  {prescription.prescription}
                </div>
              </div>

              {/* Impact */}
              <div>
                <h4 className="flex items-center gap-2 text-sm font-medium text-white mb-2">
                  <Target size={14} className="text-sentinel-400" />
                  Impact
                </h4>
                <p className="text-sm text-gray-400">{prescription.impact}</p>
              </div>

              {/* Code hint */}
              {prescription.codeHint && (
                <div>
                  <h4 className="flex items-center gap-2 text-sm font-medium text-white mb-2">
                    <Code size={14} className="text-sentinel-400" />
                    Implementation Hint
                  </h4>
                  <code className="text-xs text-sentinel-300 bg-dark-card p-3 rounded-lg block font-mono">
                    {prescription.codeHint}
                  </code>
                </div>
              )}

              {/* Footer */}
              <div className="flex items-center justify-between text-xs pt-2">
                {prescription.affectedStage && (
                  <span className="text-gray-500">
                    Affected Stage:{" "}
                    <span className="text-gray-400 capitalize">
                      {prescription.affectedStage}
                    </span>
                  </span>
                )}
                <span className={effortLabels[prescription.effort].color}>
                  {effortLabels[prescription.effort].text}
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
