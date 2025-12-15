"use client";

import { useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Terminal, Pause, Play, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn, formatLatency } from "@/lib/utils";

interface TraceEvent {
  id: string;
  timestamp: number;
  stage: string;
  latency: number;
  type: "normal" | "spike" | "backpressure" | "drop";
  message?: string;
}

interface LiveFeedProps {
  events: TraceEvent[];
  isPaused: boolean;
  onPauseToggle: () => void;
  onClear: () => void;
  maxEvents?: number;
}

const EVENT_COLORS = {
  normal: "text-gray-400",
  spike: "text-yellow-400",
  backpressure: "text-blue-400",
  drop: "text-red-400",
};

const STAGE_COLORS = {
  ingress: "text-blue-400",
  core: "text-green-400",
  risk: "text-orange-400",
  egress: "text-purple-400",
};

export function LiveFeed({
  events,
  isPaused,
  onPauseToggle,
  onClear,
  maxEvents = 100,
}: LiveFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isPaused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, isPaused]);

  const displayEvents = events.slice(-maxEvents);

  return (
    <Card className="bg-dark-card border-dark-border">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Terminal size={18} className="text-sentinel-400" />
            Live Trace Feed
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              {events.length} events
            </Badge>
            <Button
              variant="ghost"
              size="icon"
              onClick={onPauseToggle}
              title={isPaused ? "Resume" : "Pause"}
            >
              {isPaused ? <Play size={16} /> : <Pause size={16} />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={onClear}
              title="Clear"
            >
              <Trash2 size={16} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea
          ref={scrollRef}
          className="h-64 rounded-lg bg-dark-bg border border-dark-border"
        >
          <div className="p-3 font-mono text-xs space-y-1">
            <AnimatePresence mode="popLayout">
              {displayEvents.map((event) => (
                <motion.div
                  key={event.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 10 }}
                  transition={{ duration: 0.15 }}
                  className={cn(
                    "flex items-center gap-2",
                    EVENT_COLORS[event.type]
                  )}
                >
                  {/* Timestamp */}
                  <span className="text-gray-600 w-20">
                    {event.timestamp.toFixed(3)}s
                  </span>

                  {/* Stage */}
                  <span
                    className={cn(
                      "w-16 uppercase text-[10px]",
                      STAGE_COLORS[event.stage as keyof typeof STAGE_COLORS] ||
                        "text-gray-400"
                    )}
                  >
                    [{event.stage}]
                  </span>

                  {/* Latency */}
                  <span className="w-16 text-right">
                    {formatLatency(event.latency)}
                  </span>

                  {/* Event Type Badge */}
                  {event.type !== "normal" && (
                    <span
                      className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] uppercase",
                        event.type === "spike" && "bg-yellow-500/20",
                        event.type === "backpressure" && "bg-blue-500/20",
                        event.type === "drop" && "bg-red-500/20"
                      )}
                    >
                      {event.type}
                    </span>
                  )}

                  {/* Optional Message */}
                  {event.message && (
                    <span className="text-gray-500 truncate flex-1">
                      {event.message}
                    </span>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>

            {events.length === 0 && (
              <div className="text-gray-500 text-center py-8">
                Waiting for trace events...
              </div>
            )}

            {isPaused && events.length > 0 && (
              <div className="text-yellow-400 text-center py-2 bg-yellow-500/10 rounded mt-2">
                Feed paused
              </div>
            )}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
