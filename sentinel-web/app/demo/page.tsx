"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Play, Square, RotateCcw, Settings } from "lucide-react";
import { TraceTimeline } from "@/components/demo/TraceTimeline";
import { MetricsPanel } from "@/components/demo/MetricsPanel";
import { FaultInjector } from "@/components/demo/FaultInjector";
import { LiveFeed } from "@/components/demo/LiveFeed";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TimelineSegment, LatencyMetrics, ChartDataPoint } from "@/types";

// Simulation parameters
const TICK_INTERVAL = 100; // ms
const BASE_LATENCY = 450; // ns
const LATENCY_VARIANCE = 100;

interface TraceEvent {
  id: string;
  timestamp: number;
  stage: string;
  latency: number;
  type: "normal" | "spike" | "backpressure" | "drop";
  message?: string;
}

function generateRandomLatency(base: number, variance: number, multiplier = 1) {
  return Math.round(
    (base + (Math.random() - 0.5) * variance * 2) * multiplier
  );
}

function generateSegment(
  startTime: number,
  totalLatency: number,
  hasAnomaly: boolean
): TimelineSegment[] {
  const stages = ["ingress", "core", "risk", "egress"];
  const ratios = [0.09, 0.52, 0.31, 0.08];
  let currentTime = startTime;

  return stages.map((stage, i) => {
    const duration = Math.round(totalLatency * ratios[i]);
    const segment: TimelineSegment = {
      id: `${startTime}-${stage}`,
      stage,
      startTime: currentTime,
      duration,
      anomaly: hasAnomaly && stage === "core",
    };
    currentTime += duration;
    return segment;
  });
}

export default function DemoPage() {
  const [isRunning, setIsRunning] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [budget, setBudget] = useState(850);
  const [speed, setSpeed] = useState(1);
  const [isPaused, setIsPaused] = useState(false);

  const [segments, setSegments] = useState<TimelineSegment[]>([]);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [metricsHistory, setMetricsHistory] = useState<ChartDataPoint[]>([]);
  const [currentMetrics, setCurrentMetrics] = useState<LatencyMetrics>({
    p50: 423,
    p90: 712,
    p99: 847,
    p99_9: 923,
    max: 1247,
    min: 89,
    mean: 456,
    stdDev: 124,
    throughput: 284535,
  });

  const [activeFaults, setActiveFaults] = useState<Set<string>>(new Set());

  // Simulation tick
  useEffect(() => {
    if (!isRunning || isPaused) return;

    const interval = setInterval(() => {
      setCurrentTime((t) => t + TICK_INTERVAL / 1000);

      // Generate new trace event
      const hasSpike = activeFaults.has("spike") || Math.random() < 0.02;
      const hasBackpressure = activeFaults.has("backpressure");
      const hasDrop = activeFaults.has("drop") && Math.random() < 0.05;

      if (hasDrop) {
        // Add drop event
        setEvents((prev) => [
          ...prev,
          {
            id: `event-${Date.now()}`,
            timestamp: currentTime,
            stage: "egress",
            latency: 0,
            type: "drop",
            message: "Packet dropped",
          },
        ]);
      } else {
        const latencyMultiplier = hasSpike ? 3 + Math.random() * 2 : 1;
        const latency = generateRandomLatency(
          BASE_LATENCY,
          LATENCY_VARIANCE,
          latencyMultiplier
        );

        // Generate segments
        const newSegments = generateSegment(currentTime * 1000, latency, hasSpike);
        setSegments((prev) => [...prev.slice(-200), ...newSegments]);

        // Generate event
        const eventType = hasSpike
          ? "spike"
          : hasBackpressure
          ? "backpressure"
          : "normal";
        const stages = ["ingress", "core", "risk", "egress"];
        const stage = stages[Math.floor(Math.random() * stages.length)];

        setEvents((prev) => [
          ...prev,
          {
            id: `event-${Date.now()}`,
            timestamp: currentTime,
            stage,
            latency,
            type: eventType,
          },
        ]);

        // Update metrics
        setCurrentMetrics((prev) => {
          const newP99 = hasSpike
            ? Math.min(prev.p99 * 1.1, 1500)
            : Math.max(prev.p99 * 0.99, 800);
          const newMax = hasSpike ? Math.max(prev.max, latency) : prev.max * 0.995;
          return {
            ...prev,
            p50: Math.round(prev.p50 + (Math.random() - 0.5) * 20),
            p90: Math.round(prev.p90 + (Math.random() - 0.5) * 30),
            p99: Math.round(newP99),
            max: Math.round(newMax),
            throughput: Math.round(prev.throughput + (Math.random() - 0.5) * 5000),
          };
        });
      }

      // Update history every second
      if (Math.floor(currentTime) > Math.floor(currentTime - TICK_INTERVAL / 1000)) {
        setMetricsHistory((prev) => [
          ...prev.slice(-60),
          {
            time: Math.floor(currentTime),
            p50: currentMetrics.p50,
            p90: currentMetrics.p90,
            p99: currentMetrics.p99,
            max: currentMetrics.max,
          },
        ]);
      }
    }, TICK_INTERVAL / speed);

    return () => clearInterval(interval);
  }, [isRunning, isPaused, speed, currentTime, activeFaults, currentMetrics]);

  const handleStart = () => {
    setIsRunning(true);
    setIsPaused(false);
  };

  const handleStop = () => {
    setIsRunning(false);
  };

  const handleReset = () => {
    setIsRunning(false);
    setCurrentTime(0);
    setSegments([]);
    setEvents([]);
    setMetricsHistory([]);
    setActiveFaults(new Set());
    setCurrentMetrics({
      p50: 423,
      p90: 712,
      p99: 847,
      p99_9: 923,
      max: 1247,
      min: 89,
      mean: 456,
      stdDev: 124,
      throughput: 284535,
    });
  };

  const handleFaultInject = useCallback(
    (fault: { type: string; duration: number }) => {
      setActiveFaults((prev) => new Set([...prev, fault.type]));
      setTimeout(() => {
        setActiveFaults((prev) => {
          const next = new Set(prev);
          next.delete(fault.type);
          return next;
        });
      }, fault.duration * 100);
    },
    []
  );

  return (
    <div className="min-h-screen pt-20 pb-8 bg-dark-bg">
      <div className="container mx-auto px-4">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8"
        >
          <h1 className="text-3xl font-bold mb-2">Live Demo</h1>
          <p className="text-gray-400">
            Interactive trace visualization with real-time metrics and fault
            injection
          </p>
        </motion.div>

        {/* Controls */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mb-6"
        >
          <Card className="bg-dark-card border-dark-border">
            <CardContent className="py-4">
              <div className="flex flex-wrap items-center gap-6">
                {/* Playback Controls */}
                <div className="flex items-center gap-2">
                  {!isRunning ? (
                    <Button onClick={handleStart} className="gap-2">
                      <Play size={16} />
                      Start Simulation
                    </Button>
                  ) : (
                    <Button
                      onClick={handleStop}
                      variant="destructive"
                      className="gap-2"
                    >
                      <Square size={16} />
                      Stop
                    </Button>
                  )}
                  <Button variant="outline" onClick={handleReset} className="gap-2">
                    <RotateCcw size={16} />
                    Reset
                  </Button>
                </div>

                {/* Speed Control */}
                <div className="flex items-center gap-3">
                  <Label className="text-sm text-gray-400">Speed:</Label>
                  <div className="w-32">
                    <Slider
                      value={[speed]}
                      onValueChange={([v]) => setSpeed(v)}
                      min={0.5}
                      max={4}
                      step={0.5}
                    />
                  </div>
                  <span className="text-sm font-mono w-12">{speed}x</span>
                </div>

                {/* Budget Control */}
                <div className="flex items-center gap-3">
                  <Label className="text-sm text-gray-400">Budget:</Label>
                  <div className="w-32">
                    <Slider
                      value={[budget]}
                      onValueChange={([v]) => setBudget(v)}
                      min={500}
                      max={1500}
                      step={50}
                    />
                  </div>
                  <span className="text-sm font-mono w-16">{budget}ns</span>
                </div>

                {/* Time Display */}
                <div className="ml-auto text-right">
                  <div className="text-2xl font-mono text-sentinel-400">
                    {currentTime.toFixed(2)}s
                  </div>
                  <div className="text-xs text-gray-500">Simulation Time</div>
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Main Content Grid */}
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Left Column - Timeline and Metrics */}
          <div className="lg:col-span-2 space-y-6">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
            >
              <TraceTimeline
                segments={segments}
                currentTime={currentTime * 1000}
                onTimeSelect={(time) => console.log("Selected:", time)}
              />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <MetricsPanel
                metrics={currentMetrics}
                history={metricsHistory}
                budget={budget}
                isLive={isRunning && !isPaused}
              />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
            >
              <LiveFeed
                events={events}
                isPaused={isPaused}
                onPauseToggle={() => setIsPaused(!isPaused)}
                onClear={() => setEvents([])}
              />
            </motion.div>
          </div>

          {/* Right Column - Fault Injector */}
          <div className="space-y-6">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <FaultInjector
                onFaultInject={handleFaultInject}
                isRunning={isRunning}
              />
            </motion.div>

            {/* Active Faults Display */}
            {activeFaults.size > 0 && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
              >
                <Card className="bg-red-500/10 border-red-500/30">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm text-red-400">
                      Active Faults
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="flex flex-wrap gap-2">
                      {Array.from(activeFaults).map((fault) => (
                        <span
                          key={fault}
                          className="px-2 py-1 bg-red-500/20 rounded text-red-400 text-sm capitalize"
                        >
                          {fault}
                        </span>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            {/* Info Card */}
            <Card className="bg-dark-card border-dark-border">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Settings size={16} className="text-sentinel-400" />
                  About This Demo
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-gray-400 space-y-2">
                <p>
                  This simulation demonstrates Sentinel-HFT's real-time trace
                  visualization and fault injection capabilities.
                </p>
                <ul className="list-disc list-inside space-y-1">
                  <li>Watch latency metrics update in real-time</li>
                  <li>Inject faults to see how the system responds</li>
                  <li>Observe anomaly detection in action</li>
                  <li>Adjust budget to see pass/fail status change</li>
                </ul>
                <p className="text-xs text-gray-500 mt-4">
                  In production, this would connect to your live FPGA trace
                  stream via the Sentinel-HFT API.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
