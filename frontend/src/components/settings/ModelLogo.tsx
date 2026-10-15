/* eslint-disable @next/next/no-img-element -- tiny static SVG logos, nothing for next/image to optimise */
import { Brain } from "lucide-react";
import { cn } from "cn";
import baidu from "@lobehub/icons-static-svg/icons/baidu-color.svg";
import claude from "@lobehub/icons-static-svg/icons/claude-color.svg";
import cohere from "@lobehub/icons-static-svg/icons/cohere-color.svg";
import deepseek from "@lobehub/icons-static-svg/icons/deepseek-color.svg";
import gemini from "@lobehub/icons-static-svg/icons/gemini-color.svg";
import ibm from "@lobehub/icons-static-svg/icons/ibm.svg";
import kimi from "@lobehub/icons-static-svg/icons/kimi-color.svg";
import meta from "@lobehub/icons-static-svg/icons/meta-color.svg";
import microsoft from "@lobehub/icons-static-svg/icons/microsoft-color.svg";
import minimax from "@lobehub/icons-static-svg/icons/minimax-color.svg";
import mistral from "@lobehub/icons-static-svg/icons/mistral-color.svg";
import nova from "@lobehub/icons-static-svg/icons/nova-color.svg";
import nvidia from "@lobehub/icons-static-svg/icons/nvidia-color.svg";
import ollama from "@lobehub/icons-static-svg/icons/ollama.svg";
import openai from "@lobehub/icons-static-svg/icons/openai.svg";
import openrouter from "@lobehub/icons-static-svg/icons/openrouter.svg";
import qwen from "@lobehub/icons-static-svg/icons/qwen-color.svg";
import xai from "@lobehub/icons-static-svg/icons/xai.svg";
import yi from "@lobehub/icons-static-svg/icons/yi-color.svg";
import zhipu from "@lobehub/icons-static-svg/icons/zhipu-color.svg";
import type { ModelInfo } from "@/lib/types";

type Src = { src: string } | string;
const url = (s: Src) => (typeof s === "string" ? s : s.src);

// vendor (GET /api/models) → its logo (lobehub icons, MIT). `mono` ones are one colour (currentColor): drawn as a
// mask so they follow the text colour in light and dark.
const VENDORS: Record<string, { src: Src; name: string; mono?: boolean }> = {
  anthropic: { src: claude, name: "Anthropic" },
  qwen: { src: qwen, name: "Qwen (Alibaba)" },
  openai: { src: openai, name: "OpenAI", mono: true },
  google: { src: gemini, name: "Google" },
  meta: { src: meta, name: "Meta" },
  mistral: { src: mistral, name: "Mistral AI" },
  deepseek: { src: deepseek, name: "DeepSeek" },
  xai: { src: xai, name: "xAI", mono: true },
  microsoft: { src: microsoft, name: "Microsoft" },
  nvidia: { src: nvidia, name: "NVIDIA" },
  cohere: { src: cohere, name: "Cohere" },
  moonshot: { src: kimi, name: "Moonshot AI" },
  zhipu: { src: zhipu, name: "Zhipu AI" },
  minimax: { src: minimax, name: "MiniMax" },
  baidu: { src: baidu, name: "Baidu" },
  ibm: { src: ibm, name: "IBM", mono: true },
  amazon: { src: nova, name: "Amazon" },
  yi: { src: yi, name: "01.AI" },
};
const SERVERS: Record<string, { src: Src; name: string }> = {
  openrouter: { src: openrouter, name: "OpenRouter" },
  ollama: { src: ollama, name: "Ollama" },
};

export const vendorName = (vendor: string | null | undefined) => (vendor && VENDORS[vendor]?.name) || null;

function Mark({ src, mono, size, title }: { src: Src; mono?: boolean; size: number; title?: string }) {
  if (mono) {
    return (
      <span
        role={title ? "img" : undefined}
        aria-label={title}
        aria-hidden={title ? undefined : true}
        className="inline-block shrink-0 bg-current"
        style={{ width: size, height: size, mask: `url(${url(src)}) center / contain no-repeat`, WebkitMask: `url(${url(src)}) center / contain no-repeat` }}
      />
    );
  }
  return <img src={url(src)} alt={title ?? ""} aria-hidden={title ? undefined : true} width={size} height={size} className="shrink-0" />;
}

/** The logo of the company whose model it is (Claude's for Anthropic, Qwen's for Alibaba's Qwen, …). */
export function ModelLogo({ model, size = 16, className }: { model: Pick<ModelInfo, "vendor"> | null | undefined; size?: number; className?: string }) {
  const v = model?.vendor ? VENDORS[model.vendor] : undefined;
  return (
    <span className={cn("inline-flex shrink-0 items-center justify-center", className)} style={{ width: size, height: size }}>
      {v ? <Mark src={v.src} mono={v.mono} size={size} title={v.name} /> : <Brain size={size * 0.9} className="text-muted-foreground" aria-hidden />}
    </span>
  );
}

/** Where the model runs: OpenRouter's or Ollama's logo with its name, or "own server" / "this computer". */
export function ServerBadge({ model, className }: { model: Pick<ModelInfo, "server" | "where">; className?: string }) {
  const s = SERVERS[model.server];
  return (
    <span className={cn("inline-flex items-center gap-1 text-muted-foreground", className)}>
      {s && <Mark src={s.src} mono size={11} />}
      {model.where}
    </span>
  );
}
