"use client";

import { useState, useEffect } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Key,
  Copy,
  Check,
  RefreshCw,
  Crown,
  Terminal,
  AlertTriangle,
  ExternalLink,
  CreditCard,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { DashboardData } from "@/app/api/user/dashboard/route";

export default function DashboardPage() {
  const { isSignedIn, isLoaded } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showKey, setShowKey] = useState(false);
  const [copied, setCopied] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    if (isLoaded && !isSignedIn) {
      router.push("/sign-in?redirect_url=/dashboard");
    }
  }, [isLoaded, isSignedIn, router]);

  useEffect(() => {
    if (isSignedIn) {
      fetchDashboard();
    }
  }, [isSignedIn]);

  const fetchDashboard = async () => {
    try {
      const res = await fetch("/api/user/dashboard");
      if (res.ok) {
        const dashboardData = await res.json();
        setData(dashboardData);
      }
    } catch (error) {
      console.error("Failed to fetch dashboard:", error);
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = async () => {
    if (data?.licenseKey) {
      await navigator.clipboard.writeText(data.licenseKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const regenerateKey = async () => {
    if (!confirm("Are you sure? Your current key will stop working immediately.")) {
      return;
    }

    setRegenerating(true);
    try {
      const res = await fetch("/api/user/regenerate-key", { method: "POST" });
      if (res.ok) {
        await fetchDashboard();
        setShowKey(true);
      } else {
        const error = await res.json();
        alert(error.error || "Failed to regenerate key");
      }
    } catch (error) {
      console.error("Failed to regenerate key:", error);
    } finally {
      setRegenerating(false);
    }
  };

  if (!isLoaded || loading) {
    return (
      <div className="min-h-screen pt-20 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-sentinel-500" />
      </div>
    );
  }

  if (!isSignedIn) {
    return null;
  }

  const isPaid = data?.plan && data.plan !== "free";

  return (
    <div className="min-h-screen pt-20 pb-12 px-4">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">Dashboard</h1>
          <p className="text-gray-400">Manage your subscription and CLI access</p>
        </div>

        {/* Plan Status */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-dark-card border border-dark-border rounded-lg p-6 mb-6"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div
                className={cn(
                  "p-2 rounded-lg",
                  isPaid ? "bg-sentinel-500/20" : "bg-gray-500/20"
                )}
              >
                <Crown className={isPaid ? "text-sentinel-400" : "text-gray-400"} size={24} />
              </div>
              <div>
                <h2 className="text-xl font-semibold">{data?.planDisplayName || "Free"} Plan</h2>
                {data?.subscription && (
                  <p className="text-sm text-gray-400">
                    {data.subscription.cancelAtPeriodEnd
                      ? `Cancels ${new Date(data.subscription.currentPeriodEnd!).toLocaleDateString()}`
                      : `Renews ${new Date(data.subscription.currentPeriodEnd!).toLocaleDateString()}`}
                  </p>
                )}
              </div>
            </div>
            {isPaid ? (
              <a
                href={process.env.NEXT_PUBLIC_STRIPE_CUSTOMER_PORTAL_URL || "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors"
              >
                <CreditCard size={16} />
                Manage Billing
                <ExternalLink size={14} />
              </a>
            ) : (
              <Button onClick={() => router.push("/pricing")} size="sm">
                Upgrade
              </Button>
            )}
          </div>

          {!isPaid && (
            <div className="bg-sentinel-500/10 border border-sentinel-500/20 rounded-lg p-4">
              <p className="text-sm text-sentinel-300">
                Upgrade to Pro for full prescription code, Slack alerts, and CLI license key.
              </p>
            </div>
          )}
        </motion.div>

        {/* License Key Section */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-dark-card border border-dark-border rounded-lg p-6 mb-6"
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 rounded-lg bg-blue-500/20">
              <Key className="text-blue-400" size={24} />
            </div>
            <div>
              <h2 className="text-xl font-semibold">License Key</h2>
              <p className="text-sm text-gray-400">Use this key in your CLI</p>
            </div>
          </div>

          {isPaid && data?.licenseKey ? (
            <div className="space-y-4">
              {/* Key Display */}
              <div className="bg-dark-bg rounded-lg p-4 font-mono text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">
                    {showKey ? data.licenseKey : data.maskedKey}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setShowKey(!showKey)}
                      className="text-gray-400 hover:text-white text-xs"
                    >
                      {showKey ? "Hide" : "Show"}
                    </button>
                    <button
                      onClick={copyToClipboard}
                      className="p-1.5 rounded hover:bg-dark-border transition-colors"
                      title="Copy to clipboard"
                    >
                      {copied ? (
                        <Check size={16} className="text-green-400" />
                      ) : (
                        <Copy size={16} className="text-gray-400" />
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* CLI Usage */}
              <div className="bg-dark-bg rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2 text-sm text-gray-400">
                  <Terminal size={14} />
                  Quick Setup
                </div>
                <code className="text-sm text-sentinel-400 block">
                  export SENTINEL_LICENSE_KEY=&quot;{showKey ? data.licenseKey : "sl_live_..."}&quot;
                </code>
              </div>

              {/* Regenerate Key */}
              <div className="flex items-center justify-between pt-2">
                <div className="flex items-center gap-2 text-sm text-gray-400">
                  <AlertTriangle size={14} />
                  Created {data.licenseCreatedAt
                    ? new Date(data.licenseCreatedAt).toLocaleDateString()
                    : "recently"}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={regenerateKey}
                  disabled={regenerating}
                >
                  {regenerating ? (
                    <RefreshCw size={14} className="animate-spin mr-2" />
                  ) : (
                    <RefreshCw size={14} className="mr-2" />
                  )}
                  Regenerate Key
                </Button>
              </div>
            </div>
          ) : (
            <div className="bg-dark-bg rounded-lg p-6 text-center">
              <Key size={32} className="mx-auto mb-3 text-gray-500" />
              <p className="text-gray-400 mb-4">
                License keys are available on paid plans.
              </p>
              <Button onClick={() => router.push("/pricing")}>
                Upgrade to Pro
              </Button>
            </div>
          )}
        </motion.div>

        {/* CLI Documentation */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="bg-dark-card border border-dark-border rounded-lg p-6"
        >
          <h2 className="text-xl font-semibold mb-4">Getting Started with CLI</h2>

          <div className="space-y-4">
            <div className="bg-dark-bg rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-2">1. Install the CLI</h3>
              <code className="text-sm text-sentinel-400">pip install sentinel-hft</code>
            </div>

            <div className="bg-dark-bg rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-2">2. Set your license key</h3>
              <code className="text-sm text-sentinel-400">
                export SENTINEL_LICENSE_KEY=&quot;your-key-here&quot;
              </code>
            </div>

            <div className="bg-dark-bg rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-2">3. Run analysis</h3>
              <code className="text-sm text-sentinel-400">
                sentinel-hft analyze trace.bin --prescribe
              </code>
            </div>
          </div>

          <div className="mt-4 pt-4 border-t border-dark-border">
            <a
              href="/docs"
              className="text-sentinel-400 hover:text-sentinel-300 text-sm flex items-center gap-1"
            >
              View full documentation
              <ExternalLink size={14} />
            </a>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
