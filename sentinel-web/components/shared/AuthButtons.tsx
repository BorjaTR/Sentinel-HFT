"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

interface AuthButtonsProps {
  size?: "sm" | "lg";
  onNavigate?: () => void;
}

// Check if Clerk is properly configured
function useClerkEnabled() {
  const [isEnabled, setIsEnabled] = useState(false);

  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
    const enabled =
      key !== undefined &&
      key !== "" &&
      (key.startsWith("pk_test_") || key.startsWith("pk_live_")) &&
      key.length > 20;
    setIsEnabled(enabled);
  }, []);

  return isEnabled;
}

export function AuthButtons({ size = "sm", onNavigate }: AuthButtonsProps) {
  const isClerkEnabled = useClerkEnabled();
  const [ClerkComponents, setClerkComponents] = useState<{
    SignedIn: React.ComponentType<{ children: React.ReactNode }>;
    SignedOut: React.ComponentType<{ children: React.ReactNode }>;
    UserButton: React.ComponentType<{
      afterSignOutUrl?: string;
      appearance?: { elements?: { avatarBox?: string } };
    }>;
  } | null>(null);

  useEffect(() => {
    if (isClerkEnabled) {
      import("@clerk/nextjs").then((mod) => {
        setClerkComponents({
          SignedIn: mod.SignedIn,
          SignedOut: mod.SignedOut,
          UserButton: mod.UserButton,
        });
      });
    }
  }, [isClerkEnabled]);

  // If Clerk is not enabled, show default auth buttons
  if (!isClerkEnabled || !ClerkComponents) {
    return (
      <>
        <Button variant="ghost" size={size} asChild>
          <Link href="/sign-in" onClick={onNavigate}>
            Sign In
          </Link>
        </Button>
        <Button
          size={size}
          className="bg-sentinel-500 hover:bg-sentinel-600"
          asChild
        >
          <Link href="/sign-up" onClick={onNavigate}>
            Get Started
          </Link>
        </Button>
      </>
    );
  }

  const { SignedIn, SignedOut, UserButton } = ClerkComponents;

  return (
    <>
      <SignedOut>
        <Button variant="ghost" size={size} asChild>
          <Link href="/sign-in" onClick={onNavigate}>
            Sign In
          </Link>
        </Button>
        <Button
          size={size}
          className="bg-sentinel-500 hover:bg-sentinel-600"
          asChild
        >
          <Link href="/sign-up" onClick={onNavigate}>
            Get Started
          </Link>
        </Button>
      </SignedOut>

      <SignedIn>
        <UserButton
          afterSignOutUrl="/"
          appearance={{
            elements: {
              avatarBox: size === "lg" ? "w-10 h-10" : "w-8 h-8",
            },
          }}
        />
      </SignedIn>
    </>
  );
}
