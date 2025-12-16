"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { useAuth } from "@/hooks/useAuth";
import { useSubscription } from "@/hooks/useSubscription";
import { AnalysisChat } from "@/components/analyze/AnalysisChat";
import { SettingsPanel } from "@/components/analyze/SettingsPanel";
import { UpgradeModal } from "@/components/analyze/UpgradeModal";
import { PerformanceDoctor } from "@/components/analyze/PerformanceDoctor";
import { AnalysisSettings, AnalysisResult } from "@/types";
import { Button } from "@/components/ui/button";
import { Settings, X, ChevronRight, Crown, MessageSquare, Stethoscope } from "lucide-react";
import { cn } from "@/lib/utils";

type ViewMode = "chat" | "doctor";

const DEFAULT_SETTINGS: AnalysisSettings = {
  budget: 850,
  percentile: "p99",
  showAttribution: true,
  detectAnomalies: true,
  anomalyThreshold: 3,
};

export default function AnalyzePage() {
  const { isSignedIn } = useAuth();
  const { isPro } = useSubscription();
  const [settings, setSettings] = useState<AnalysisSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);

  // isDemo is true when user is not Pro (either not signed in or free tier)
  const isDemo = !isPro;

  return (
    <div className="min-h-screen pt-16 bg-dark-bg">
      <div className="flex h-[calc(100vh-4rem)]">
        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col">
          {/* Header */}
          <div className="border-b border-dark-border px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div>
                <h1 className="text-lg font-semibold">AI Analysis</h1>
                <p className="text-sm text-gray-400">
                  {isDemo
                    ? "Demo mode - exploring sample trace"
                    : "Analyze your trace data"}
                </p>
              </div>
              {isPro && (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-sentinel-500/20 text-sentinel-400 text-xs rounded-full">
                  <Crown size={12} />
                  Pro
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* View Mode Tabs */}
              <div className="flex items-center bg-dark-card rounded-lg p-1">
                <button
                  onClick={() => setViewMode("chat")}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                    viewMode === "chat"
                      ? "bg-sentinel-500 text-white"
                      : "text-gray-400 hover:text-white"
                  )}
                >
                  <MessageSquare size={16} />
                  <span className="hidden sm:inline">Chat</span>
                </button>
                <button
                  onClick={() => setViewMode("doctor")}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                    viewMode === "doctor"
                      ? "bg-sentinel-500 text-white"
                      : "text-gray-400 hover:text-white"
                  )}
                >
                  <Stethoscope size={16} />
                  <span className="hidden sm:inline">Doctor</span>
                </button>
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
          </div>

          {/* Main Content */}
          {viewMode === "chat" ? (
            <AnalysisChat
              settings={settings}
              isDemo={isDemo}
              isPro={isPro}
              isSignedIn={isSignedIn}
              onUpgradeClick={() => setShowUpgradeModal(true)}
            />
          ) : (
            <div className="flex-1 overflow-y-auto p-4">
              <PerformanceDoctor
                analysisResult={analysisResult}
                isDemo={isDemo}
              />
            </div>
          )}
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

      {/* Upgrade Modal */}
      <UpgradeModal
        open={showUpgradeModal}
        onClose={() => setShowUpgradeModal(false)}
        isSignedIn={isSignedIn}
      />
    </div>
  );
}
