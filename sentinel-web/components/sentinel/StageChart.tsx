"use client";

import ReactECharts from "echarts-for-react";
import { useMemo } from "react";

export interface StageDatum {
  stage: string;
  p50: number;
  p99: number;
  mean: number;
}

/**
 * Per-stage latency bars (p50, p99) across ingress / core / risk / egress.
 *
 * Dark trading-floor palette, values plotted in microseconds with
 * auto-scale and ns-labeled tooltip.
 */
export default function StageChart({ data }: { data: StageDatum[] | null }) {
  const option = useMemo(() => {
    const rows = data ?? [];
    const stages = rows.map((r) => r.stage);
    const p50 = rows.map((r) => +(r.p50 / 1_000).toFixed(2));
    const p99 = rows.map((r) => +(r.p99 / 1_000).toFixed(2));

    return {
      backgroundColor: "transparent",
      grid: { top: 24, right: 16, bottom: 32, left: 52 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#0a0e14",
        borderColor: "#1f2a38",
        borderWidth: 1,
        textStyle: { color: "#d5e0ea", fontFamily: "ui-monospace, monospace", fontSize: 11 },
        axisPointer: { type: "shadow", shadowStyle: { color: "rgba(34,211,238,0.08)" } },
        valueFormatter: (v: number) =>
          v < 1_000 ? `${v.toFixed(2)} µs` : `${(v / 1_000).toFixed(2)} ms`,
      },
      legend: {
        data: ["p50", "p99"],
        top: 0,
        right: 0,
        textStyle: { color: "#9ab3c8", fontFamily: "ui-monospace, monospace", fontSize: 10 },
        itemGap: 16,
        icon: "roundRect",
        itemWidth: 10,
        itemHeight: 10,
      },
      xAxis: {
        type: "category",
        data: stages,
        axisLine: { lineStyle: { color: "#1a232e" } },
        axisLabel: { color: "#9ab3c8", fontFamily: "ui-monospace, monospace", fontSize: 10 },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        axisLabel: {
          color: "#4d617a",
          fontFamily: "ui-monospace, monospace",
          fontSize: 10,
          formatter: (v: number) => (v < 1_000 ? `${v.toFixed(0)} µs` : `${(v / 1_000).toFixed(1)} ms`),
        },
        splitLine: { lineStyle: { color: "#1a232e" } },
      },
      series: [
        {
          name: "p50",
          type: "bar",
          data: p50,
          barMaxWidth: 28,
          itemStyle: {
            color: "#10b981",
            borderRadius: [2, 2, 0, 0],
          },
        },
        {
          name: "p99",
          type: "bar",
          data: p99,
          barMaxWidth: 28,
          itemStyle: {
            color: "#22d3ee",
            borderRadius: [2, 2, 0, 0],
          },
        },
      ],
    };
  }, [data]);

  if (!data || !data.length) {
    return (
      <div className="flex h-60 items-center justify-center font-mono text-xs text-[#4d617a]">
        no stage samples yet…
      </div>
    );
  }

  return (
    <ReactECharts
      option={option}
      style={{ height: 240, width: "100%" }}
      opts={{ renderer: "canvas" }}
      notMerge
      lazyUpdate
    />
  );
}
