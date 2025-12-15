"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AnalysisChat } from "@/components/analyze/AnalysisChat";
import { SettingsPanel } from "@/components/analyze/SettingsPanel";
import { AnalysisSettings } from "@/types";
import { Button } from "@/components/ui/button";
import { Settings, X, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const DEFAULT_SETTINGS: AnalysisSettings = {
  budget: 850,
  percentile: "p99",
  showAttribution: true,
  detectAnomalies: true,
  anomalyThreshold: 3,
};

export default function AnalyzePage() {
  const [settings, setSettings] = useState<AnalysisSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const isDemo = true; // Will be based on auth status

  return (
    <div className="min-h-screen pt-16 bg-dark-bg">
      <div className="flex h-[calc(100vh-4rem)]">
        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col">
          {/* Header */}
          <div className="border-b border-dark-border px-4 py-3 flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold">AI Analysis</h1>
              <p className="text-sm text-gray-400">
                {isDemo
                  ? "Demo mode - exploring sample trace"
                  : "Analyze your trace data"}
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowSettings(!showSettings)}
              className="lg:hidden"
            >
              {showSettings ? <X size={18} /> : <Settings size={18} />}
            </Button>
          </div>

          {/* Chat Interface */}
          <AnalysisChat settings={settings} isDemo={isDemo} />
        </div>

        {/* Settings Sidebar - Desktop */}
        <motion.aside
          initial={false}
          animate={{
            width: showSettings ? 320 : 0,
            opacity: showSettings ? 1 : 0,
          }}
          className={cn(
            "hidden lg:block border-l border-dark-border overflow-hidden",
            showSettings ? "p-4" : "p-0"
          )}
        >
          <SettingsPanel
            settings={settings}
            onSettingsChange={setSettings}
            isDemo={isDemo}
          />
        </motion.aside>

        {/* Settings Toggle - Desktop */}
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="hidden lg:flex items-center justify-center w-6 border-l border-dark-border bg-dark-card hover:bg-dark-border transition-colors"
          title={showSettings ? "Hide settings" : "Show settings"}
        >
          <ChevronRight
            size={16}
            className={cn(
              "text-gray-400 transition-transform",
              showSettings && "rotate-180"
            )}
          />
        </button>
      </div>

      {/* Settings Panel - Mobile (Overlay) */}
      {showSettings && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 20 }}
          className="lg:hidden fixed inset-x-0 bottom-0 z-50 bg-dark-bg border-t border-dark-border p-4 max-h-[60vh] overflow-y-auto"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Settings</h2>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowSettings(false)}
            >
              <X size={18} />
            </Button>
          </div>
          <SettingsPanel
            settings={settings}
            onSettingsChange={setSettings}
            isDemo={isDemo}
          />
        </motion.div>
      )}
    </div>
  );
}
