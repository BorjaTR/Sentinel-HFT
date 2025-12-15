"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Loader2, Sparkles, Upload, FileText } from "lucide-react";
import { Message, AnalysisSettings, AnalysisResult } from "@/types";
import { MessageBubble } from "./MessageBubble";
import { ResultsDisplay } from "./ResultsDisplay";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { findDemoResponse, getDemoAnalysisResult } from "@/data/demo-responses";

interface AnalysisChatProps {
  settings: AnalysisSettings;
  isDemo: boolean;
}

const INITIAL_MESSAGES: Message[] = [
  {
    id: "welcome",
    role: "assistant",
    content: `Welcome to Sentinel-HFT AI Analysis! I'm here to help you understand your FPGA trading system latency.

**In demo mode**, I'm analyzing a pre-loaded trace file with 1.2M records. You can ask me about:

- **Overview**: "Analyze this trace" or "What does this data show?"
- **Bottlenecks**: "Where are the bottlenecks?" or "What's causing latency?"
- **Anomalies**: "Show me the latency spikes" or "What anomalies did you find?"
- **Specific stages**: "Tell me about the risk stage" or "What about egress latency?"

Try asking a question to get started!`,
    timestamp: new Date(),
  },
];

const SUGGESTED_QUERIES = [
  "Analyze this trace file",
  "Where are the bottlenecks?",
  "Show me the latency spikes",
  "What's the P99 latency?",
  "Explain the attribution breakdown",
];

export function AnalysisChat({ settings, isDemo }: AnalysisChatProps) {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Scroll to bottom when new messages are added
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    // Simulate API delay for demo
    await new Promise((resolve) => setTimeout(resolve, 1000 + Math.random() * 1000));

    if (isDemo) {
      // Use pre-computed demo response
      const demoResponse = findDemoResponse(input);

      // Check if this is an analysis request
      if (
        input.toLowerCase().includes("analyze") ||
        input.toLowerCase().includes("overview") ||
        input.toLowerCase().includes("summary")
      ) {
        const result = getDemoAnalysisResult(settings.budget);
        setAnalysisResult(result);
        setShowResults(true);
      }

      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: demoResponse,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } else {
      // Real API call would go here
      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content:
          "API integration coming soon. For now, try the demo mode to explore the analysis capabilities.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    }

    setIsLoading(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSuggestedQuery = (query: string) => {
    setInput(query);
    inputRef.current?.focus();
  };

  return (
    <div className="flex flex-col h-[calc(100vh-12rem)]">
      {/* Chat Messages */}
      <ScrollArea ref={scrollRef} className="flex-1 px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          <AnimatePresence>
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </AnimatePresence>

          {/* Show analysis results after analysis request */}
          {showResults && analysisResult && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="mt-6"
            >
              <ResultsDisplay
                result={analysisResult}
                showAttribution={settings.showAttribution}
              />
            </motion.div>
          )}

          {/* Loading Indicator */}
          {isLoading && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-3 px-4 py-3"
            >
              <div className="w-8 h-8 rounded-full bg-sentinel-500/20 flex items-center justify-center">
                <Loader2 size={16} className="text-sentinel-400 animate-spin" />
              </div>
              <span className="text-gray-400 text-sm">Analyzing...</span>
            </motion.div>
          )}
        </div>
      </ScrollArea>

      {/* Suggested Queries */}
      {messages.length <= 2 && !isLoading && (
        <div className="px-4 py-3 border-t border-dark-border">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles size={14} className="text-sentinel-400" />
              <span className="text-xs text-gray-500">Try asking:</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {SUGGESTED_QUERIES.map((query) => (
                <button
                  key={query}
                  onClick={() => handleSuggestedQuery(query)}
                  className="px-3 py-1.5 text-sm rounded-full bg-dark-card border border-dark-border hover:border-sentinel-500/50 text-gray-300 hover:text-white transition-colors"
                >
                  {query}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Input Area */}
      <div className="border-t border-dark-border p-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-3">
            {/* File Upload Button (disabled in demo) */}
            <Button
              variant="outline"
              size="icon"
              disabled={isDemo}
              className="shrink-0"
              title={isDemo ? "File upload available in Pro" : "Upload trace file"}
            >
              <Upload size={18} />
            </Button>

            {/* Text Input */}
            <div className="flex-1 relative">
              <Textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your trace analysis..."
                className="min-h-[44px] max-h-32 resize-none pr-12"
                rows={1}
              />
              <Button
                size="icon"
                className="absolute right-2 top-1/2 -translate-y-1/2 h-8 w-8"
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
              >
                {isLoading ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Send size={16} />
                )}
              </Button>
            </div>
          </div>

          {/* Demo Mode Indicator */}
          {isDemo && (
            <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
              <FileText size={12} />
              <span>Demo: Analyzing sample trace (1.2M records)</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
