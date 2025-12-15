"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import * as d3 from "d3";
import { TimelineSegment } from "@/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Layers, ZoomIn, ZoomOut, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatLatency } from "@/lib/utils";

interface TraceTimelineProps {
  segments: TimelineSegment[];
  currentTime: number;
  onTimeSelect?: (time: number) => void;
}

const STAGE_COLORS: Record<string, string> = {
  ingress: "#3b82f6",
  core: "#22c55e",
  risk: "#f59e0b",
  egress: "#8b5cf6",
  idle: "#374151",
};

export function TraceTimeline({
  segments,
  currentTime,
  onTimeSelect,
}: TraceTimelineProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 200 });
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth,
          height: 200,
        });
      }
    };

    updateDimensions();
    window.addEventListener("resize", updateDimensions);
    return () => window.removeEventListener("resize", updateDimensions);
  }, []);

  useEffect(() => {
    if (!svgRef.current || segments.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const margin = { top: 20, right: 20, bottom: 40, left: 60 };
    const width = dimensions.width - margin.left - margin.right;
    const height = dimensions.height - margin.top - margin.bottom;

    const g = svg
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    // Calculate visible range based on zoom and offset
    const totalDuration = segments.reduce((sum, s) => sum + s.duration, 0);
    const visibleDuration = totalDuration / zoom;
    const startTime = offset;
    const endTime = startTime + visibleDuration;

    // Filter segments in view
    const visibleSegments = segments.filter(
      (s) => s.startTime < endTime && s.startTime + s.duration > startTime
    );

    // X scale
    const xScale = d3
      .scaleLinear()
      .domain([startTime, endTime])
      .range([0, width]);

    // Y scale for lanes
    const stages = ["ingress", "core", "risk", "egress"];
    const yScale = d3
      .scaleBand()
      .domain(stages)
      .range([0, height])
      .padding(0.2);

    // Draw segments
    g.selectAll("rect.segment")
      .data(visibleSegments)
      .enter()
      .append("rect")
      .attr("class", "segment")
      .attr("x", (d) => Math.max(0, xScale(d.startTime)))
      .attr("y", (d) => yScale(d.stage) || 0)
      .attr("width", (d) => {
        const x1 = Math.max(0, xScale(d.startTime));
        const x2 = Math.min(width, xScale(d.startTime + d.duration));
        return Math.max(0, x2 - x1);
      })
      .attr("height", yScale.bandwidth())
      .attr("fill", (d) => STAGE_COLORS[d.stage] || STAGE_COLORS.idle)
      .attr("rx", 2)
      .attr("opacity", (d) => (d.anomaly ? 1 : 0.7))
      .style("cursor", "pointer")
      .on("click", (event, d) => {
        if (onTimeSelect) onTimeSelect(d.startTime);
      })
      .on("mouseover", function (event, d) {
        d3.select(this).attr("opacity", 1);

        // Show tooltip
        const tooltip = g.append("g").attr("class", "tooltip");
        tooltip
          .append("rect")
          .attr("x", xScale(d.startTime) + 5)
          .attr("y", (yScale(d.stage) || 0) - 30)
          .attr("width", 120)
          .attr("height", 25)
          .attr("fill", "#1f2937")
          .attr("stroke", "#374151")
          .attr("rx", 4);
        tooltip
          .append("text")
          .attr("x", xScale(d.startTime) + 10)
          .attr("y", (yScale(d.stage) || 0) - 12)
          .attr("fill", "white")
          .attr("font-size", "11px")
          .text(`${d.stage}: ${formatLatency(d.duration)}`);
      })
      .on("mouseout", function () {
        d3.select(this).attr("opacity", (d: TimelineSegment) =>
          d.anomaly ? 1 : 0.7
        );
        g.selectAll(".tooltip").remove();
      });

    // Add anomaly markers
    const anomalySegments = visibleSegments.filter((s) => s.anomaly);
    g.selectAll("circle.anomaly")
      .data(anomalySegments)
      .enter()
      .append("circle")
      .attr("class", "anomaly")
      .attr("cx", (d) => xScale(d.startTime + d.duration / 2))
      .attr("cy", (d) => (yScale(d.stage) || 0) + yScale.bandwidth() / 2)
      .attr("r", 4)
      .attr("fill", "#ef4444")
      .attr("stroke", "#fca5a5")
      .attr("stroke-width", 2);

    // X axis
    const xAxis = d3
      .axisBottom(xScale)
      .ticks(8)
      .tickFormat((d) => `${d}ns`);
    g.append("g")
      .attr("transform", `translate(0,${height})`)
      .call(xAxis)
      .attr("color", "#9ca3af");

    // Y axis (stage labels)
    const yAxis = d3.axisLeft(yScale);
    g.append("g").call(yAxis).attr("color", "#9ca3af");

    // Current time indicator
    if (currentTime >= startTime && currentTime <= endTime) {
      g.append("line")
        .attr("x1", xScale(currentTime))
        .attr("x2", xScale(currentTime))
        .attr("y1", 0)
        .attr("y2", height)
        .attr("stroke", "#22c55e")
        .attr("stroke-width", 2)
        .attr("stroke-dasharray", "4,2");
    }
  }, [segments, dimensions, zoom, offset, currentTime, onTimeSelect]);

  const handleZoomIn = () => setZoom((z) => Math.min(z * 1.5, 10));
  const handleZoomOut = () => setZoom((z) => Math.max(z / 1.5, 1));
  const handleReset = () => {
    setZoom(1);
    setOffset(0);
  };

  return (
    <Card className="bg-dark-card border-dark-border">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Layers size={18} className="text-sentinel-400" />
            Trace Timeline
          </CardTitle>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={handleZoomIn}>
              <ZoomIn size={16} />
            </Button>
            <Button variant="ghost" size="icon" onClick={handleZoomOut}>
              <ZoomOut size={16} />
            </Button>
            <Button variant="ghost" size="icon" onClick={handleReset}>
              <RotateCcw size={16} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div ref={containerRef} className="w-full">
          <svg
            ref={svgRef}
            width={dimensions.width}
            height={dimensions.height}
            className="overflow-visible"
          />
        </div>
        {/* Legend */}
        <div className="flex flex-wrap gap-4 mt-4 text-sm">
          {Object.entries(STAGE_COLORS)
            .filter(([k]) => k !== "idle")
            .map(([stage, color]) => (
              <div key={stage} className="flex items-center gap-2">
                <div
                  className="w-3 h-3 rounded"
                  style={{ backgroundColor: color }}
                />
                <span className="text-gray-400 capitalize">{stage}</span>
              </div>
            ))}
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-500 border-2 border-red-300" />
            <span className="text-gray-400">Anomaly</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
