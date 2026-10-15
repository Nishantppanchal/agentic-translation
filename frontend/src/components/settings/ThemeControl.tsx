"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { setTheme, useTheme, type Theme } from "@/lib/prefs";

export const THEME_OPTIONS: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: "system", label: "System", Icon: Monitor },
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
];

/** System / Light / Dark. `compact`: one icon button that cycles through them (for the sidebar). */
export function ThemeControl({ compact = false, side = "top" }: { compact?: boolean; side?: "top" | "right" }) {
  const theme = useTheme();
  if (compact) {
    const i = THEME_OPTIONS.findIndex((o) => o.value === theme);
    const { Icon, label } = THEME_OPTIONS[i];
    const next = THEME_OPTIONS[(i + 1) % THEME_OPTIONS.length];
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setTheme(next.value)}
            className="text-muted-foreground hover:text-foreground"
            aria-label={`Theme: ${label}. Switch to ${next.label}`}
          >
            <Icon />
          </Button>
        </TooltipTrigger>
        <TooltipContent side={side}>
          Theme: {label} (click for {next.label})
        </TooltipContent>
      </Tooltip>
    );
  }
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      value={theme}
      onValueChange={(v) => v && setTheme(v as Theme)}
      aria-label="Theme"
    >
      {THEME_OPTIONS.map(({ value, label, Icon }) => (
        <ToggleGroupItem key={value} value={value} className="gap-1.5 px-3 text-xs data-[state=on]:bg-primary-soft data-[state=on]:text-primary">
          <Icon /> {label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
