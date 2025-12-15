"use client";

import { motion } from "framer-motion";
import { Settings, Info, HelpCircle } from "lucide-react";
import { AnalysisSettings } from "@/types";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface SettingsPanelProps {
  settings: AnalysisSettings;
  onSettingsChange: (settings: AnalysisSettings) => void;
  isDemo: boolean;
}

export function SettingsPanel({
  settings,
  onSettingsChange,
  isDemo,
}: SettingsPanelProps) {
  const updateSetting = <K extends keyof AnalysisSettings>(
    key: K,
    value: AnalysisSettings[K]
  ) => {
    onSettingsChange({ ...settings, [key]: value });
  };

  return (
    <Card className="bg-dark-card border-dark-border">
      <CardHeader className="pb-4">
        <CardTitle className="text-base flex items-center gap-2">
          <Settings size={18} className="text-sentinel-400" />
          Analysis Settings
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Demo Mode Indicator */}
        {isDemo && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-start gap-2 p-3 rounded-lg bg-sentinel-500/10 border border-sentinel-500/20"
          >
            <Info size={16} className="text-sentinel-400 mt-0.5 shrink-0" />
            <div className="text-sm">
              <span className="text-sentinel-400 font-medium">Demo Mode</span>
              <p className="text-gray-400 mt-0.5">
                Using pre-computed analysis results. Upgrade to Pro to analyze
                your own traces.
              </p>
            </div>
          </motion.div>
        )}

        {/* Budget Setting */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-2">
              Latency Budget
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle size={14} className="text-gray-500" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="max-w-xs">
                    Maximum acceptable P99 latency in nanoseconds. Traces
                    exceeding this will be flagged.
                  </p>
                </TooltipContent>
              </Tooltip>
            </Label>
            <span className="text-sm font-mono text-sentinel-400">
              {settings.budget}ns
            </span>
          </div>
          <Slider
            value={[settings.budget]}
            onValueChange={([value]) => updateSetting("budget", value)}
            min={100}
            max={2000}
            step={50}
            className="w-full"
          />
          <div className="flex justify-between text-xs text-gray-500">
            <span>100ns</span>
            <span>2000ns</span>
          </div>
        </div>

        {/* Percentile Selection */}
        <div className="space-y-2">
          <Label className="flex items-center gap-2">
            Focus Percentile
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle size={14} className="text-gray-500" />
              </TooltipTrigger>
              <TooltipContent>
                <p className="max-w-xs">
                  Which percentile to use for budget comparisons.
                </p>
              </TooltipContent>
            </Tooltip>
          </Label>
          <Select
            value={settings.percentile}
            onValueChange={(value) =>
              updateSetting("percentile", value as AnalysisSettings["percentile"])
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="p50">P50 (Median)</SelectItem>
              <SelectItem value="p90">P90</SelectItem>
              <SelectItem value="p99">P99</SelectItem>
              <SelectItem value="p99.9">P99.9</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Attribution Toggle */}
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2">
            Show Attribution
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle size={14} className="text-gray-500" />
              </TooltipTrigger>
              <TooltipContent>
                <p className="max-w-xs">
                  Break down latency by pipeline stage (ingress, core, risk,
                  egress).
                </p>
              </TooltipContent>
            </Tooltip>
          </Label>
          <Switch
            checked={settings.showAttribution}
            onCheckedChange={(checked) =>
              updateSetting("showAttribution", checked)
            }
          />
        </div>

        {/* Anomaly Detection Toggle */}
        <div className="flex items-center justify-between">
          <Label className="flex items-center gap-2">
            Anomaly Detection
            <Tooltip>
              <TooltipTrigger>
                <HelpCircle size={14} className="text-gray-500" />
              </TooltipTrigger>
              <TooltipContent>
                <p className="max-w-xs">
                  Automatically detect latency spikes, backpressure events, and
                  other anomalies.
                </p>
              </TooltipContent>
            </Tooltip>
          </Label>
          <Switch
            checked={settings.detectAnomalies}
            onCheckedChange={(checked) =>
              updateSetting("detectAnomalies", checked)
            }
          />
        </div>

        {/* Threshold Setting */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-2">
              Anomaly Threshold
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle size={14} className="text-gray-500" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="max-w-xs">
                    Standard deviations from mean to consider as an anomaly.
                  </p>
                </TooltipContent>
              </Tooltip>
            </Label>
            <span className="text-sm font-mono text-gray-400">
              {settings.anomalyThreshold}σ
            </span>
          </div>
          <Slider
            value={[settings.anomalyThreshold]}
            onValueChange={([value]) => updateSetting("anomalyThreshold", value)}
            min={1}
            max={5}
            step={0.5}
            className="w-full"
          />
        </div>

        {/* API Key (disabled in demo) */}
        <div className="space-y-2">
          <Label className="flex items-center gap-2 text-gray-400">
            API Key
            {isDemo && (
              <span className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-500">
                Pro only
              </span>
            )}
          </Label>
          <Input
            type="password"
            placeholder="sk-..."
            disabled={isDemo}
            value={settings.apiKey || ""}
            onChange={(e) => updateSetting("apiKey", e.target.value)}
            className="font-mono text-sm"
          />
        </div>
      </CardContent>
    </Card>
  );
}
