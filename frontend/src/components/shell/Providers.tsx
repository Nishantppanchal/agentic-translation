"use client";

import { MotionConfig } from "motion/react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

/** App-wide providers: tooltips (one shared delay), motion that honours the system's reduce-motion setting, toasts. */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={300}>
        {children}
        <Toaster position="bottom-right" closeButton />
      </TooltipProvider>
    </MotionConfig>
  );
}
