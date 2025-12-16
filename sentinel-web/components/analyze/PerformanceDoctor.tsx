"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Stethoscope,
  Activity,
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  Filter,
  ChevronDown,
} from "lucide-react";
import { DiagnosisReport, PrescriptionSeverity, AnalysisResult } from "@/types";
import { PrescriptionCard } from "./PrescriptionCard";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { generateDiagnosisReport, getDemoDiagnosisReport } from "@/lib/prescriptions";

interface PerformanceDoctorProps {
  analysisResult?: AnalysisResult | null;
  isDemo?: boolean;
  onClose?: () => void;
}

const healthConfig = {
  healthy: {
    color: "text-green-400",
    bgColor: "bg-green-500/10",
    borderColor: "border-green-500/30",
    icon: CheckCircle,
    label: "Healthy",
  },
  warning: {
    color: "text-yellow-400",
    bgColor: "bg-yellow-500/10",
    borderColor: "border-yellow-500/30",
    icon: AlertTriangle,
    label: "Needs Attention",
  },
  critical: {
    color: "text-red-400",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
    icon: AlertCircle,
    label: "Critical",
  },
};

type FilterOption = "all" | PrescriptionSeverity;

export function PerformanceDoctor({
  analysisResult,
  isDemo = true,
  onClose,
}: PerformanceDoctorProps) {
  const [report, setReport] = useState<DiagnosisReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState<FilterOption>("all");
  const [showFilterMenu, setShowFilterMenu] = useState(false);

  useEffect(() => {
    // Generate diagnosis report
    setIsLoading(true);

    // Simulate a brief loading state for better UX
    const timer = setTimeout(() => {
      if (analysisResult) {
        setReport(generateDiagnosisReport(analysisResult));
      } else if (isDemo) {
        setReport(getDemoDiagnosisReport());
      }
      setIsLoading(false);
    }, 500);

    return () => clearTimeout(timer);
  }, [analysisResult, isDemo]);

  const handleRefresh = () => {
    setIsLoading(true);
    setTimeout(() => {
      if (analysisResult) {
        setReport(generateDiagnosisReport(analysisResult));
      } else if (isDemo) {
        setReport(getDemoDiagnosisReport());
      }
      setIsLoading(false);
    }, 500);
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
        >
          <Stethoscope className="w-12 h-12 text-sentinel-400" />
        </motion.div>
        <p className="text-gray-400 mt-4">Diagnosing system health...</p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="text-center py-16 text-gray-400">
        No analysis data available. Run an analysis first.
      </div>
    );
  }

  const config = healthConfig[report.overallHealth];
  const HealthIcon = config.icon;

  const filteredPrescriptions =
    filter === "all"
      ? report.prescriptions
      : report.prescriptions.filter((p) => p.severity === filter);

  const filterOptions: { value: FilterOption; label: string; count: number }[] = [
    { value: "all", label: "All", count: report.prescriptions.length },
    {
      value: "critical",
      label: "Critical",
      count: report.prescriptions.filter((p) => p.severity === "critical").length,
    },
    {
      value: "warning",
      label: "Warning",
      count: report.prescriptions.filter((p) => p.severity === "warning").length,
    },
    {
      value: "info",
      label: "Info",
      count: report.prescriptions.filter((p) => p.severity === "info").length,
    },
    {
      value: "success",
      label: "Success",
      count: report.prescriptions.filter((p) => p.severity === "success").length,
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-sentinel-500/20 rounded-lg">
            <Stethoscope className="w-6 h-6 text-sentinel-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">Performance Doctor</h2>
            <p className="text-sm text-gray-400">
              {isDemo ? "Demo Analysis" : "Live Analysis"} - Generated{" "}
              {report.timestamp.toLocaleTimeString()}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            className="gap-2"
          >
            <RefreshCw size={14} />
            Refresh
          </Button>
          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose}>
              Close
            </Button>
          )}
        </div>
      </div>

      {/* Health Score Card */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className={cn(
          "rounded-xl border p-6",
          config.bgColor,
          config.borderColor
        )}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={cn("p-3 rounded-full", config.bgColor)}>
              <HealthIcon className={cn("w-8 h-8", config.color)} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className={cn("text-2xl font-bold", config.color)}>
                  {config.label}
                </span>
                <span className="text-4xl font-bold text-white">
                  {report.healthScore}
                </span>
                <span className="text-lg text-gray-400">/100</span>
              </div>
              <p className="text-gray-400 mt-1">{report.summary}</p>
            </div>
          </div>

          {/* Quick Stats */}
          <div className="hidden md:flex items-center gap-6">
            <div className="text-center">
              <div className="flex items-center gap-1 text-red-400">
                <AlertCircle size={16} />
                <span className="text-2xl font-bold">
                  {report.metrics.criticalCount}
                </span>
              </div>
              <span className="text-xs text-gray-500">Critical</span>
            </div>
            <div className="text-center">
              <div className="flex items-center gap-1 text-yellow-400">
                <AlertTriangle size={16} />
                <span className="text-2xl font-bold">
                  {report.metrics.warningCount}
                </span>
              </div>
              <span className="text-xs text-gray-500">Warnings</span>
            </div>
            <div className="text-center">
              <div className="flex items-center gap-1 text-blue-400">
                <Activity size={16} />
                <span className="text-2xl font-bold">
                  {report.metrics.optimizationCount}
                </span>
              </div>
              <span className="text-xs text-gray-500">Optimizations</span>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Filter Bar */}
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-white">
          Prescriptions ({filteredPrescriptions.length})
        </h3>

        <div className="relative">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowFilterMenu(!showFilterMenu)}
            className="gap-2"
          >
            <Filter size={14} />
            {filter === "all" ? "All" : filter.charAt(0).toUpperCase() + filter.slice(1)}
            <ChevronDown size={14} />
          </Button>

          {showFilterMenu && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="absolute right-0 mt-2 w-48 bg-dark-card border border-dark-border rounded-lg shadow-lg z-10"
            >
              {filterOptions.map((option) => (
                <button
                  key={option.value}
                  onClick={() => {
                    setFilter(option.value);
                    setShowFilterMenu(false);
                  }}
                  className={cn(
                    "w-full px-4 py-2 text-left text-sm flex items-center justify-between hover:bg-dark-border transition-colors",
                    filter === option.value && "bg-dark-border"
                  )}
                >
                  <span>{option.label}</span>
                  <span className="text-gray-500">{option.count}</span>
                </button>
              ))}
            </motion.div>
          )}
        </div>
      </div>

      {/* Prescriptions List */}
      <div className="space-y-4">
        {filteredPrescriptions.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            No prescriptions match the selected filter.
          </div>
        ) : (
          filteredPrescriptions.map((prescription, index) => (
            <PrescriptionCard
              key={prescription.id}
              prescription={prescription}
              index={index}
            />
          ))
        )}
      </div>

      {/* Footer */}
      {isDemo && (
        <div className="text-center text-sm text-gray-500 pt-4 border-t border-dark-border">
          This is a demo analysis. Upgrade to Pro to analyze your own traces.
        </div>
      )}
    </div>
  );
}
