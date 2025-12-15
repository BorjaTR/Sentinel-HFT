"use client";

import { motion } from "framer-motion";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { AnalysisResult, Anomaly } from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, CheckCircle, Clock, Activity, Layers } from "lucide-react";
import { cn, formatLatency } from "@/lib/utils";

interface ResultsDisplayProps {
  result: AnalysisResult;
  showAttribution: boolean;
}

const COLORS = {
  ingress: "#3b82f6",
  core: "#22c55e",
  risk: "#f59e0b",
  egress: "#8b5cf6",
};

function MetricCard({
  label,
  value,
  unit,
  status,
}: {
  label: string;
  value: string | number;
  unit?: string;
  status?: "pass" | "fail" | "warn";
}) {
  return (
    <div className="metric-card p-4 rounded-xl">
      <div className="text-gray-400 text-sm mb-1">{label}</div>
      <div className="flex items-baseline gap-1">
        <span
          className={cn(
            "text-2xl font-bold font-mono",
            status === "pass" && "text-sentinel-400",
            status === "fail" && "text-red-400",
            status === "warn" && "text-yellow-400",
            !status && "text-white"
          )}
        >
          {value}
        </span>
        {unit && <span className="text-gray-500 text-sm">{unit}</span>}
      </div>
    </div>
  );
}

function AnomalyCard({ anomaly }: { anomaly: Anomaly }) {
  const severityColors = {
    low: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    medium: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    high: "bg-red-500/20 text-red-400 border-red-500/30",
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      className={cn(
        "p-3 rounded-lg border",
        severityColors[anomaly.severity]
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} />
          <span className="font-medium text-sm">{anomaly.type}</span>
        </div>
        <Badge
          variant={
            anomaly.severity === "high"
              ? "destructive"
              : anomaly.severity === "medium"
              ? "warning"
              : "secondary"
          }
          className="text-xs"
        >
          {anomaly.severity}
        </Badge>
      </div>
      <p className="text-sm mt-2 opacity-80">{anomaly.description}</p>
      <div className="flex gap-4 mt-2 text-xs opacity-60">
        <span>t={anomaly.timestamp.toFixed(3)}s</span>
        {anomaly.affectedStage && <span>Stage: {anomaly.affectedStage}</span>}
      </div>
    </motion.div>
  );
}

export function ResultsDisplay({ result, showAttribution }: ResultsDisplayProps) {
  const latencyData = [
    { name: "P50", value: result.metrics.p50, fill: "#6b7280" },
    { name: "P90", value: result.metrics.p90, fill: "#3b82f6" },
    { name: "P99", value: result.metrics.p99, fill: "#22c55e" },
    { name: "P99.9", value: result.metrics.p99_9, fill: "#f59e0b" },
    { name: "Max", value: result.metrics.max, fill: "#ef4444" },
  ];

  const attributionData = result.attribution
    ? [
        { name: "Ingress", value: result.attribution.ingress, color: COLORS.ingress },
        { name: "Core", value: result.attribution.core, color: COLORS.core },
        { name: "Risk", value: result.attribution.risk, color: COLORS.risk },
        { name: "Egress", value: result.attribution.egress, color: COLORS.egress },
      ]
    : [];

  const budgetStatus = result.budgetMet ? "pass" : "fail";

  return (
    <div className="space-y-6">
      {/* Status Banner */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className={cn(
          "flex items-center gap-3 p-4 rounded-xl border",
          result.budgetMet
            ? "bg-sentinel-500/10 border-sentinel-500/30"
            : "bg-red-500/10 border-red-500/30"
        )}
      >
        {result.budgetMet ? (
          <CheckCircle className="text-sentinel-400" size={24} />
        ) : (
          <AlertTriangle className="text-red-400" size={24} />
        )}
        <div>
          <div className="font-semibold">
            {result.budgetMet
              ? "All latency budgets met"
              : "Latency budget exceeded"}
          </div>
          <div className="text-sm text-gray-400">
            P99: {formatLatency(result.metrics.p99)} (budget:{" "}
            {formatLatency(result.budget)})
          </div>
        </div>
      </motion.div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="P99 Latency"
          value={formatLatency(result.metrics.p99)}
          status={budgetStatus}
        />
        <MetricCard
          label="Throughput"
          value={(result.metrics.throughput / 1000).toFixed(0)}
          unit="K/sec"
        />
        <MetricCard
          label="Total Records"
          value={(result.totalRecords / 1000000).toFixed(2)}
          unit="M"
        />
        <MetricCard
          label="Anomalies"
          value={result.anomalies.length}
          status={result.anomalies.length > 0 ? "warn" : "pass"}
        />
      </div>

      {/* Latency Distribution Chart */}
      <Card className="bg-dark-card border-dark-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Clock size={18} className="text-sentinel-400" />
            Latency Distribution
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="name" stroke="#9ca3af" fontSize={12} />
                <YAxis
                  stroke="#9ca3af"
                  fontSize={12}
                  tickFormatter={(v) => `${v}ns`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#1f2937",
                    border: "1px solid #374151",
                    borderRadius: "8px",
                  }}
                  formatter={(value: number) => [`${value}ns`, "Latency"]}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {latencyData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Attribution Breakdown */}
      {showAttribution && result.attribution && (
        <Card className="bg-dark-card border-dark-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Layers size={18} className="text-sentinel-400" />
              Latency Attribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-2 gap-6">
              {/* Pie Chart */}
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={attributionData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={80}
                      paddingAngle={2}
                      dataKey="value"
                    >
                      {attributionData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#1f2937",
                        border: "1px solid #374151",
                        borderRadius: "8px",
                      }}
                      formatter={(value: number) => [`${value}%`, "Share"]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              {/* Legend */}
              <div className="flex flex-col justify-center gap-3">
                {attributionData.map((item) => (
                  <div key={item.name} className="flex items-center gap-3">
                    <div
                      className="w-4 h-4 rounded"
                      style={{ backgroundColor: item.color }}
                    />
                    <span className="text-gray-300 flex-1">{item.name}</span>
                    <span className="font-mono text-white">{item.value}%</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Anomalies */}
      {result.anomalies.length > 0 && (
        <Card className="bg-dark-card border-dark-border">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Activity size={18} className="text-sentinel-400" />
              Detected Anomalies
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {result.anomalies.map((anomaly, index) => (
                <AnomalyCard key={index} anomaly={anomaly} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
