"use client";

import { useEffect, useMemo, useRef } from "react";
import uPlot, { type AlignedData, type Options } from "uplot";
import "uplot/dist/uPlot.min.css";

/**
 * Streaming p99 latency line chart.
 *
 * Renders a dense, low-chrome uPlot line over the last ~120 progress snapshots.
 * Designed for a trading-floor dark shell: cyan stroke, emerald fill,
 * no legend, minimal axes.
 */
export default function LatencyChart({
  history,
}: {
  history: Array<[number, number]>;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);

  const data: AlignedData = useMemo(() => {
    if (!history.length) return [[0], [0]] as unknown as AlignedData;
    const xs = history.map((p) => p[0]);
    const ys = history.map((p) => p[1] / 1_000); // ns -> µs for legibility
    return [xs, ys] as unknown as AlignedData;
  }, [history]);

  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;

    const opts: Options = {
      width: el.clientWidth || 480,
      height: 240,
      padding: [8, 16, 8, 8],
      scales: { x: { time: false }, y: { auto: true } },
      legend: { show: false },
      cursor: {
        drag: { x: false, y: false },
        points: { size: 6, fill: "#34d399" },
      },
      axes: [
        {
          stroke: "#4d617a",
          grid: { stroke: "#1a232e", width: 1 },
          ticks: { stroke: "#1a232e", width: 1 },
          font: "10px ui-monospace, monospace",
          values: (_u, ticks) => ticks.map((t) => `${t.toFixed(1)}s`),
        },
        {
          stroke: "#4d617a",
          grid: { stroke: "#1a232e", width: 1 },
          ticks: { stroke: "#1a232e", width: 1 },
          font: "10px ui-monospace, monospace",
          size: 50,
          values: (_u, ticks) =>
            ticks.map((t) => (t < 1000 ? `${t.toFixed(0)} µs` : `${(t / 1000).toFixed(1)} ms`)),
        },
      ],
      series: [
        {},
        {
          label: "p99",
          stroke: "#22d3ee",
          width: 1.5,
          fill: "rgba(16, 185, 129, 0.08)",
          points: { show: false },
        },
      ],
    };

    const u = new uPlot(opts, data, el);
    plotRef.current = u;

    const ro = new ResizeObserver(() => {
      u.setSize({ width: el.clientWidth, height: 240 });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      u.destroy();
      plotRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    plotRef.current?.setData(data);
  }, [data]);

  if (!history.length) {
    return (
      <div className="flex h-60 items-center justify-center font-mono text-xs text-[#4d617a]">
        waiting for ticks…
      </div>
    );
  }

  return <div ref={containerRef} className="h-60 w-full" />;
}
