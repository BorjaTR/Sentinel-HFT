"use client";

import ReactECharts from "echarts-for-react";
import { useMemo } from "react";

export interface RejectData {
  passed: number;
  toxic: number;
  rate: number;
  position: number;
  notional: number;
  order_size: number;
  kill: number;
}

/**
 * Sankey of intent flow through the pre-gate filter and the risk gate,
 * ending at PASSED or a terminal REJECT bucket.
 *
 * intents --> pre-gate --> { toxic, kill, risk-gate }
 * risk-gate --> { rate, pos, notional, order_size, PASSED }
 */
export default function RejectSankey({ data }: { data: RejectData | null }) {
  const option = useMemo(() => {
    const d = data ?? {
      passed: 0,
      toxic: 0,
      rate: 0,
      position: 0,
      notional: 0,
      order_size: 0,
      kill: 0,
    };

    const preTotal =
      d.passed + d.toxic + d.rate + d.position + d.notional + d.order_size + d.kill;
    const riskIn = d.passed + d.rate + d.position + d.notional + d.order_size;

    // Only include links whose value is > 0 so echarts doesn't draw flat ribbons.
    const links = [
      { source: "intents", target: "pre-gate", value: preTotal },
      { source: "pre-gate", target: "toxic", value: d.toxic },
      { source: "pre-gate", target: "kill", value: d.kill },
      { source: "pre-gate", target: "risk-gate", value: riskIn },
      { source: "risk-gate", target: "rate", value: d.rate },
      { source: "risk-gate", target: "pos", value: d.position },
      { source: "risk-gate", target: "notional", value: d.notional },
      { source: "risk-gate", target: "order-size", value: d.order_size },
      { source: "risk-gate", target: "PASSED", value: d.passed },
    ].filter((l) => l.value > 0);

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: "#0a0e14",
        borderColor: "#1f2a38",
        borderWidth: 1,
        textStyle: { color: "#d5e0ea", fontFamily: "ui-monospace, monospace", fontSize: 11 },
      },
      series: [
        {
          type: "sankey",
          left: 8,
          right: 80,
          top: 12,
          bottom: 12,
          nodeAlign: "justify",
          nodeWidth: 10,
          nodeGap: 8,
          emphasis: { focus: "adjacency" },
          lineStyle: { color: "gradient", curveness: 0.5, opacity: 0.35 },
          label: {
            color: "#9ab3c8",
            fontFamily: "ui-monospace, monospace",
            fontSize: 10,
            formatter: (p: { name: string; value: number }) =>
              `${p.name} · ${p.value?.toLocaleString?.() ?? p.value}`,
          },
          data: [
            { name: "intents", itemStyle: { color: "#22d3ee" } },
            { name: "pre-gate", itemStyle: { color: "#6366f1" } },
            { name: "risk-gate", itemStyle: { color: "#8b5cf6" } },
            { name: "toxic", itemStyle: { color: "#f43f5e" } },
            { name: "kill", itemStyle: { color: "#f59e0b" } },
            { name: "rate", itemStyle: { color: "#ef4444" } },
            { name: "pos", itemStyle: { color: "#ef4444" } },
            { name: "notional", itemStyle: { color: "#ef4444" } },
            { name: "order-size", itemStyle: { color: "#ef4444" } },
            { name: "PASSED", itemStyle: { color: "#10b981" } },
          ],
          links,
        },
      ],
    };
  }, [data]);

  if (!data) {
    return (
      <div className="flex h-60 items-center justify-center font-mono text-xs text-[#4d617a]">
        waiting for decisions…
      </div>
    );
  }

  const total =
    data.passed +
    data.toxic +
    data.rate +
    data.position +
    data.notional +
    data.order_size +
    data.kill;

  if (total === 0) {
    return (
      <div className="flex h-60 items-center justify-center font-mono text-xs text-[#4d617a]">
        0 intents decided so far
      </div>
    );
  }

  return (
    <ReactECharts
      option={option}
      style={{ height: 260, width: "100%" }}
      opts={{ renderer: "canvas" }}
      notMerge
      lazyUpdate
    />
  );
}
