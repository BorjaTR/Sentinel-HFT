"use client";

import { motion } from "framer-motion";
import { User, Bot, Paperclip, Download } from "lucide-react";
import { Message, Attachment } from "@/types";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";

interface MessageBubbleProps {
  message: Message;
}

function AttachmentPreview({ attachment }: { attachment: Attachment }) {
  if (attachment.type === "trace") {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-dark-card border border-dark-border text-sm">
        <Paperclip size={14} className="text-sentinel-400" />
        <span className="text-gray-300">{attachment.name}</span>
        {attachment.size && (
          <span className="text-gray-500">
            ({(attachment.size / 1024).toFixed(1)} KB)
          </span>
        )}
      </div>
    );
  }

  if (attachment.type === "report" && attachment.data) {
    return (
      <div className="mt-2 p-4 rounded-lg bg-dark-card border border-dark-border">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium text-gray-300">
            Analysis Report
          </span>
          <button className="text-sentinel-400 hover:text-sentinel-300 text-sm flex items-center gap-1">
            <Download size={14} />
            Export
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-gray-500">Records</div>
            <div className="text-white font-mono">
              {attachment.data.totalRecords?.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-gray-500">P99 Latency</div>
            <div className="text-white font-mono">
              {attachment.data.p99Latency}ns
            </div>
          </div>
          <div>
            <div className="text-gray-500">Throughput</div>
            <div className="text-white font-mono">
              {attachment.data.throughput?.toLocaleString()}/sec
            </div>
          </div>
          <div>
            <div className="text-gray-500">Anomalies</div>
            <div
              className={cn(
                "font-mono",
                attachment.data.anomalyCount && attachment.data.anomalyCount > 0
                  ? "text-red-400"
                  : "text-sentinel-400"
              )}
            >
              {attachment.data.anomalyCount}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return null;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn("flex gap-3", isUser && "flex-row-reverse")}
    >
      {/* Avatar */}
      <div
        className={cn(
          "w-8 h-8 rounded-full flex items-center justify-center shrink-0",
          isUser
            ? "bg-blue-500/20 text-blue-400"
            : "bg-sentinel-500/20 text-sentinel-400"
        )}
      >
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      {/* Message Content */}
      <div
        className={cn(
          "flex-1 max-w-[80%]",
          isUser && "flex flex-col items-end"
        )}
      >
        <div
          className={cn(
            "rounded-2xl px-4 py-3",
            isUser
              ? "bg-blue-500/20 border border-blue-500/30"
              : "bg-dark-card border border-dark-border"
          )}
        >
          {/* Attachments */}
          {message.attachments && message.attachments.length > 0 && (
            <div className="mb-2 space-y-2">
              {message.attachments.map((attachment, index) => (
                <AttachmentPreview key={index} attachment={attachment} />
              ))}
            </div>
          )}

          {/* Text Content */}
          <div className="prose prose-invert prose-sm max-w-none">
            <ReactMarkdown
              components={{
                p: ({ children }) => (
                  <p className="text-gray-300 mb-2 last:mb-0">{children}</p>
                ),
                strong: ({ children }) => (
                  <strong className="text-white font-semibold">{children}</strong>
                ),
                code: ({ children }) => (
                  <code className="px-1.5 py-0.5 rounded bg-dark-bg text-sentinel-400 font-mono text-xs">
                    {children}
                  </code>
                ),
                pre: ({ children }) => (
                  <pre className="p-3 rounded-lg bg-dark-bg overflow-x-auto my-2">
                    {children}
                  </pre>
                ),
                ul: ({ children }) => (
                  <ul className="list-disc list-inside space-y-1 text-gray-300">
                    {children}
                  </ul>
                ),
                ol: ({ children }) => (
                  <ol className="list-decimal list-inside space-y-1 text-gray-300">
                    {children}
                  </ol>
                ),
                li: ({ children }) => (
                  <li className="text-gray-300">{children}</li>
                ),
                h3: ({ children }) => (
                  <h3 className="text-white font-semibold text-base mt-3 mb-2">
                    {children}
                  </h3>
                ),
                h4: ({ children }) => (
                  <h4 className="text-white font-medium text-sm mt-2 mb-1">
                    {children}
                  </h4>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        </div>

        {/* Timestamp */}
        <span className="text-xs text-gray-500 mt-1 px-2">
          {message.timestamp.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </motion.div>
  );
}
