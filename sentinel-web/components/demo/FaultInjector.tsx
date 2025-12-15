"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Zap, Clock, AlertTriangle, Activity, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface FaultConfig {
  type: "spike" | "backpressure" | "clockDrift" | "drop";
  enabled: boolean;
  intensity: number;
  duration: number;
}

interface FaultInjectorProps {
  onFaultInject: (fault: FaultConfig) => void;
  isRunning: boolean;
}

const FAULT_TYPES = [
  {
    id: "spike" as const,
    label: "Latency Spike",
    description: "Inject sudden latency increase",
    icon: Zap,
    color: "text-yellow-400",
    bgColor: "bg-yellow-400/10",
    maxIntensity: 500,
    unit: "ns",
  },
  {
    id: "backpressure" as const,
    label: "Backpressure",
    description: "Simulate downstream congestion",
    icon: Activity,
    color: "text-blue-400",
    bgColor: "bg-blue-400/10",
    maxIntensity: 100,
    unit: "cycles",
  },
  {
    id: "clockDrift" as const,
    label: "Clock Drift",
    description: "Add timing jitter",
    icon: Clock,
    color: "text-purple-400",
    bgColor: "bg-purple-400/10",
    maxIntensity: 50,
    unit: "ppm",
  },
  {
    id: "drop" as const,
    label: "Packet Drop",
    description: "Random message loss",
    icon: AlertTriangle,
    color: "text-red-400",
    bgColor: "bg-red-400/10",
    maxIntensity: 10,
    unit: "%",
  },
];

export function FaultInjector({ onFaultInject, isRunning }: FaultInjectorProps) {
  const [faults, setFaults] = useState<Record<string, FaultConfig>>({
    spike: { type: "spike", enabled: false, intensity: 100, duration: 10 },
    backpressure: {
      type: "backpressure",
      enabled: false,
      intensity: 50,
      duration: 20,
    },
    clockDrift: {
      type: "clockDrift",
      enabled: false,
      intensity: 10,
      duration: 100,
    },
    drop: { type: "drop", enabled: false, intensity: 1, duration: 50 },
  });
  const [activeFault, setActiveFault] = useState<string | null>(null);

  const handleToggleFault = (faultId: string) => {
    setFaults((prev) => ({
      ...prev,
      [faultId]: { ...prev[faultId], enabled: !prev[faultId].enabled },
    }));
  };

  const handleIntensityChange = (faultId: string, value: number) => {
    setFaults((prev) => ({
      ...prev,
      [faultId]: { ...prev[faultId], intensity: value },
    }));
  };

  const handleInject = (faultId: string) => {
    if (!isRunning) return;

    const fault = faults[faultId];
    if (!fault.enabled) return;

    setActiveFault(faultId);
    onFaultInject(fault);

    // Clear active state after duration
    setTimeout(() => {
      setActiveFault(null);
    }, fault.duration * 100);
  };

  const enabledCount = Object.values(faults).filter((f) => f.enabled).length;

  return (
    <Card className="bg-dark-card border-dark-border">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Zap size={18} className="text-sentinel-400" />
            Fault Injection
          </CardTitle>
          {enabledCount > 0 && (
            <Badge variant="secondary" className="text-xs">
              {enabledCount} enabled
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!isRunning && (
          <div className="text-sm text-gray-400 bg-gray-800/50 rounded-lg p-3">
            Start the simulation to inject faults
          </div>
        )}

        {FAULT_TYPES.map((faultType) => {
          const fault = faults[faultType.id];
          const isActive = activeFault === faultType.id;

          return (
            <motion.div
              key={faultType.id}
              className={cn(
                "rounded-lg border p-3 transition-colors",
                fault.enabled
                  ? "border-dark-border bg-dark-bg/50"
                  : "border-transparent bg-transparent",
                isActive && "border-sentinel-500/50 bg-sentinel-500/10"
              )}
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "w-8 h-8 rounded-lg flex items-center justify-center",
                      faultType.bgColor
                    )}
                  >
                    <faultType.icon size={16} className={faultType.color} />
                  </div>
                  <div>
                    <div className="font-medium text-sm flex items-center gap-2">
                      {faultType.label}
                      {isActive && (
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500">
                      {faultType.description}
                    </div>
                  </div>
                </div>
                <Switch
                  checked={fault.enabled}
                  onCheckedChange={() => handleToggleFault(faultType.id)}
                />
              </div>

              {/* Controls */}
              <AnimatePresence>
                {fault.enabled && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="pt-3 space-y-3"
                  >
                    {/* Intensity Slider */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <Label className="text-xs text-gray-400">
                          Intensity
                        </Label>
                        <span className="text-xs font-mono text-white">
                          {fault.intensity}
                          {faultType.unit}
                        </span>
                      </div>
                      <Slider
                        value={[fault.intensity]}
                        onValueChange={([v]) =>
                          handleIntensityChange(faultType.id, v)
                        }
                        min={1}
                        max={faultType.maxIntensity}
                        step={1}
                      />
                    </div>

                    {/* Inject Button */}
                    <Button
                      size="sm"
                      variant={isActive ? "destructive" : "outline"}
                      className="w-full"
                      disabled={!isRunning || isActive}
                      onClick={() => handleInject(faultType.id)}
                    >
                      {isActive ? (
                        <>
                          <Square size={14} className="mr-2" />
                          Injecting...
                        </>
                      ) : (
                        <>
                          <Play size={14} className="mr-2" />
                          Inject Now
                        </>
                      )}
                    </Button>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          );
        })}
      </CardContent>
    </Card>
  );
}
