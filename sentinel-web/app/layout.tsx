import type { Metadata } from "next";
import { ClerkProviderWrapper } from "@/components/providers/ClerkProviderWrapper";
import { Navigation } from "@/components/shared/Navigation";
import { Footer } from "@/components/shared/Footer";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sentinel-HFT | FPGA-Grade Latency Verification",
  description:
    "Catch nanosecond regressions before they cost real money. Hardware-level tracing with AI-powered root cause analysis for high-frequency trading systems.",
  keywords: [
    "FPGA",
    "HFT",
    "latency",
    "verification",
    "trading",
    "RTL",
    "observability",
  ],
  authors: [{ name: "Sentinel-HFT Team" }],
  openGraph: {
    title: "Sentinel-HFT | FPGA-Grade Latency Verification",
    description:
      "Catch nanosecond regressions before they cost real money. Hardware-level tracing with AI-powered root cause analysis.",
    type: "website",
    url: "https://sentinel-hft.dev",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "Sentinel-HFT",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Sentinel-HFT | FPGA-Grade Latency Verification",
    description:
      "Catch nanosecond regressions before they cost real money.",
    images: ["/og-image.png"],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="font-sans antialiased bg-dark-bg text-white">
        <ClerkProviderWrapper>
          <TooltipProvider>
            <Navigation />
            <main className="min-h-screen">{children}</main>
            <Footer />
          </TooltipProvider>
        </ClerkProviderWrapper>
      </body>
    </html>
  );
}
