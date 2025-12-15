"use client";

import { motion } from "framer-motion";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { ChartDataPoint, LatencyMetrics } from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, TrendingUp, AlertTriangle, CheckCircle } from "lucide-react";
import { cn, formatLatency, formatNumber } from "@/lib/utils";

interface MetricsPanelProps {
  metrics: LatencyMetrics;
  history: ChartDataPoint[];
  budget: number;
  isLive: boolean;
}

function MetricBox({
  label,
  value,
  unit,
  trend,
  status,
}: {
  label: string;
  value: number | string;
  unit?: string;
  trend?: "up" | "down" | "stable";
  status?: "good" | "warning" | "bad";
}) {
  return (
    <div className="metric-card p-3 rounded-lg">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-400">{label}</span>
        {trend && (
          <TrendingUp
            size={12}
            className={cn(
              trend === "up" && "text-red-400 rotate-0",
              trend === "down" && "text-green-400 rotate-180",
              trend === "stable" && "text-gray-400 rotate-90"
            )}
          />
        )}
      </div>
      <div className="flex items-baseline gap-1">
        <span
          className={cn(
            "text-xl font-bold font-mono",
            status === "good" && "text-sentinel-400",
            status === "warning" && "text-yellow-400",
            status === "bad" && "text-red-400",
            !status && "text-white"
          )}
        >
          {value}
        </span>
        {unit && <span className="text-xs text-gray-500">{unit}</span>}
      </div>
    </div>
  );
}

export function MetricsPanel({
  metrics,
  history,
  budget,
  isLive,
}: MetricsPanelProps) {
  const budgetStatus = metrics.p99 <= budget ? "good" : "bad";
  const p99Trend =
    history.length > 1
      ? history[history.length - 1].p99 > history[history.length - 2].p99
        ? "up"
        : history[history.length - 1].p99 < history[history.length - 2].p99
        ? "down"
        : "stable"
      : "stable";

  return (
    <Card className="bg-dark-card border-dark-border">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Activity size={18} className="text-sentinel-400" />
            Live Metrics
          </CardTitle>
          {isLive && (
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sentinel-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-sentinel-500" />
              </span>
              <span className="text-xs text-sentinel-400">Live</span>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Key Metrics Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricBox
            label="P99 Latency"
            value={formatLatency(metrics.p99)}
            status={budgetStatus}
            trend={p99Trend}
          />
          <MetricBox
            label="Throughput"
            value={formatNumber(metrics.throughput)}
            unit="/sec"
          />
          <MetricBox
            label="P50 Latency"
            value={formatLatency(metrics.p50)}
          />
          <MetricBox
            label="Max Latency"
            value={formatLatency(metrics.max)}
            status={metrics.max > budget * 2 ? "warning" : undefined}
          />
        </div>

        {/* Budget Status */}
        <div
          className={cn(
            "flex items-center gap-2 px-3 py-2 rounded-lg",
            budgetStatus === "good"
              ? "bg-sentinel-500/10 border border-sentinel-500/30"
              : "bg-red-500/10 border border-red-500/30"
          )}
        >
          {budgetStatus === "good" ? (
            <CheckCircle size={16} className="text-sentinel-400" />
          ) : (
            <AlertTriangle size={16} className="text-red-400" />
          )}
          <span className="text-sm">
            P99 {budgetStatus === "good" ? "within" : "exceeds"} budget (
            {formatLatency(budget)})
          </span>
        </div>

        {/* Latency Chart */}
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="time"
                stroke="#9ca3af"
                fontSize={10}
                tickFormatter={(v) => `${v}s`}
              />
              <YAxis
                stroke="#9ca3af"
                fontSize={10}
                tickFormatter={(v) => `${v}ns`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
                formatter={(value: number, name: string) => [
                  `${value}ns`,
                  name.toUpperCase(),
                ]}
              />
              <ReferenceLine
                y={budget}
                stroke="#ef4444"
                strokeDasharray="4 4"
                label={{
                  value: "Budget",
                  position: "right",
                  fill: "#ef4444",
                  fontSize: 10,
                }}
              />
              <Line
                type="monotone"
                dataKey="p50"
                stroke="#6b7280"
                strokeWidth={1}
                dot={false}
                name="p50"
              />
              <Line
                type="monotone"
                dataKey="p99"
                stroke="#22c55e"
                strokeWidth={2}
                dot={false}
                name="p99"
              />
              <Line
                type="monotone"
                dataKey="max"
                stroke="#f59e0b"
                strokeWidth={1}
                dot={false}
                name="max"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Chart Legend */}
        <div className="flex justify-center gap-6 text-xs">
          <div className="flex items-center gap-2">
            <div className="w-3 h-0.5 bg-gray-500" />
            <span className="text-gray-400">P50</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-0.5 bg-sentinel-500" />
            <span className="text-gray-400">P99</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-0.5 bg-yellow-500" />
            <span className="text-gray-400">Max</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-0.5 bg-red-500 border-dashed" />
            <span className="text-gray-400">Budget</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
