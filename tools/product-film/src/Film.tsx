import "@fontsource-variable/inter/opsz.css";
import { useState, type CSSProperties, type ReactNode } from "react";
import { AbsoluteFill, Audio, Img, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { cameraAt, clamp, cursorAt, ease, ramp, shotsAt, type Rect, type Timeline } from "./timeline";

const themes = {
  light: {
    bg: "#f5f5f7",
    glow: "rgba(255,255,255,0.95)",
    ink: "#1d1d1f",
    muted: "#6e6e73",
    bar: "#f0f0f2",
    barLine: "rgba(0,0,0,0.08)",
    pill: "#e4e4e7",
    pillInk: "#6e6e73",
    hairline: "rgba(0,0,0,0.1)",
    shadow: "0 60px 120px -30px rgba(0,0,0,0.26), 0 30px 60px -30px rgba(0,0,0,0.22)",
    glass: "rgba(255,255,255,0.86)",
  },
  dark: {
    bg: "#000000",
    glow: "rgba(70,70,80,0.38)",
    ink: "#f5f5f7",
    muted: "#a1a1a6",
    bar: "#26262a",
    barLine: "rgba(255,255,255,0.08)",
    pill: "#38383d",
    pillInk: "#a1a1a6",
    hairline: "rgba(255,255,255,0.16)",
    shadow: "0 60px 140px -20px rgba(120,130,160,0.2), 0 30px 60px -30px rgba(0,0,0,0.9)",
    glass: "rgba(40,40,44,0.86)",
  },
};
type Theme = (typeof themes)["light"];

// Words arrive one at a time, out of a slight blur. `accent` is the coloured end of the line.
const Words = ({ text, accent, t, at, color, stagger = 0.07, rise = 24 }: { text: string; accent?: string; t: number; at: number; color: string; stagger?: number; rise?: number }) => {
  const plain = text.split(" ").map((w) => ({ w, on: false }));
  const lit = (accent ?? "").split(" ").filter(Boolean).map((w) => ({ w, on: true }));
  return (
    <>
      {[...plain, ...lit].map(({ w, on }, i) => {
        const p = ramp(t, at + i * stagger, at + i * stagger + 0.85, ease.rise);
        return (
          <span key={i} style={{ display: "inline-block", marginRight: "0.26em", opacity: clamp(p * 1.4), transform: `translateY(${(1 - p) * rise}px)`, filter: p < 1 ? `blur(${(1 - p) * 7}px)` : undefined, color: on ? color : undefined }}>
            {w}
          </span>
        );
      })}
    </>
  );
};

const Logo = ({ tl, size, style }: { tl: Timeline; size: number; style?: CSSProperties }) => {
  const { logo, logoRadius, accent } = tl.brand;
  if (logo) return <Img src={staticFile(logo)} style={{ width: size, height: size, objectFit: "contain", borderRadius: logoRadius ?? "22%", ...style }} />;
  // No logo given: a glass sphere in the brand colour.
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: `radial-gradient(circle at 36% 26%, #ffffff 0%, color-mix(in srgb, ${accent} 16%, #fff) 34%, color-mix(in srgb, ${accent} 52%, #fff) 66%, ${accent} 100%)`,
        boxShadow: `inset 0 -8px 26px color-mix(in srgb, ${accent} 42%, transparent), 0 24px 54px -16px color-mix(in srgb, ${accent} 60%, transparent)`,
        ...style,
      }}
    />
  );
};

const SceneTitle = ({ tl, t, th, z }: { tl: Timeline; t: number; th: Theme; z: number }) => {
  const scene = tl.titles.find((s) => t >= s.t0 - 0.05 && t < s.t1);
  if (!scene) return null;
  // Gone as soon as the camera pushes in, so it is never cut off by the top of the frame.
  const leave = (1 - ramp(t, scene.t1 - 0.45, scene.t1 - 0.05)) * (1 - clamp((z - 1.015) / 0.07));
  const at = scene.t0 + 0.12;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: tl.window.y, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", opacity: leave, paddingTop: 6 }}>
      {scene.eyebrow && <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.005em", color: tl.brand.accent, opacity: ramp(t, at, at + 0.5), marginBottom: 6 }}>{scene.eyebrow}</div>}
      <div style={{ fontSize: 60, fontWeight: 600, letterSpacing: "-0.024em", lineHeight: 1.08, color: th.ink }}>
        <Words text={scene.title} t={t} at={at + 0.06} color={tl.brand.accent} rise={18} />
      </div>
      {scene.body && <div style={{ fontSize: 25, fontWeight: 400, letterSpacing: "-0.008em", color: th.muted, marginTop: 8, opacity: ramp(t, at + 0.45, at + 1.05), transform: `translateY(${(1 - ramp(t, at + 0.45, at + 1.05, ease.rise)) * 10}px)` }}>{scene.body}</div>}
    </div>
  );
};

const BrowserBar = ({ tl, th }: { tl: Timeline; th: Theme }) => (
  <div style={{ height: tl.window.chromeHeight, background: th.bar, borderBottom: `1px solid ${th.barLine}`, display: "flex", alignItems: "center", position: "relative", paddingLeft: 18, gap: 9 }}>
    {["#ff5f57", "#febc2e", "#28c840"].map((c) => (
      <i key={c} style={{ width: 13, height: 13, borderRadius: "50%", background: c, boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.12)" }} />
    ))}
    {tl.window.address && (
      <div style={{ position: "absolute", left: "50%", transform: "translateX(-50%)", height: 28, minWidth: 360, padding: "0 18px", borderRadius: 8, background: th.pill, color: th.pillInk, fontSize: 14.5, fontWeight: 500, display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
        <svg width="10" height="12" viewBox="0 0 10 12"><path fill="currentColor" d="M2.2 5V3.4a2.8 2.8 0 0 1 5.6 0V5h.7c.5 0 .9.4.9.9v4.7c0 .5-.4.9-.9.9h-7c-.5 0-.9-.4-.9-.9V5.9c0-.5.4-.9.9-.9h.6Zm1.2 0h3.2V3.4a1.6 1.6 0 0 0-3.2 0V5Z" /></svg>
        {tl.window.address}
      </div>
    )}
  </div>
);

const appBox = (tl: Timeline, r: Rect, m = 0): CSSProperties => ({
  position: "absolute",
  left: (r.x - m) * tl.window.s,
  top: (r.y - m) * tl.window.s,
  width: (r.w + 2 * m) * tl.window.s,
  height: (r.h + 2 * m) * tl.window.s,
});

const AppWindow = ({ tl, t, th }: { tl: Timeline; t: number; th: Theme }) => {
  const w = tl.window;
  const { top, under, opacity } = shotsAt(tl, t);
  const fill: CSSProperties = { position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" };
  return (
    <div style={{ position: "absolute", left: w.x, top: w.y, width: w.w, height: w.h + w.chromeHeight, borderRadius: 16, overflow: "hidden", boxShadow: `${th.shadow}, 0 0 0 1px ${th.hairline}`, background: th.bar }}>
      {w.chrome === "browser" && <BrowserBar tl={tl} th={th} />}
      <div style={{ position: "relative", width: w.w, height: w.h, overflow: "hidden" }}>
        {under && <Img key={under.src} src={staticFile(under.src)} style={fill} />}
        <Img key={top.src} src={staticFile(top.src)} style={{ ...fill, opacity }} />
        {tl.spots.map((s, i) => {
          const o = Math.min(ramp(t, s.t0, s.t0 + 0.45), 1 - ramp(t, s.t1 - 0.35, s.t1));
          return o > 0 ? <div key={i} style={{ ...appBox(tl, s.rect, 8), borderRadius: 12, opacity: o, boxShadow: "0 0 0 4000px rgba(0,0,0,0.44), 0 0 0 1.5px rgba(255,255,255,0.8)" }} /> : null;
        })}
        {tl.rings.map((s, i) => {
          const o = Math.min(ramp(t, s.t0, s.t0 + 0.35), 1 - ramp(t, s.t1 - 0.3, s.t1));
          const grow = 1 + 0.04 * (1 - ramp(t, s.t0, s.t0 + 0.5, ease.rise));
          return o > 0 ? <div key={i} style={{ ...appBox(tl, s.rect, 7), borderRadius: 10, opacity: o, transform: `scale(${grow})`, boxShadow: `0 0 0 1.5px ${tl.brand.accent}, 0 0 0 5px color-mix(in srgb, ${tl.brand.accent} 18%, transparent)` }} /> : null;
        })}
      </div>
    </div>
  );
};

const Pointer = ({ tl, t, z }: { tl: Timeline; t: number; z: number }) => {
  const c = cursorAt(tl, t);
  const parts: ReactNode[] = [];
  const scale = 1 / z ** 0.55;
  for (const [i, k] of tl.clicks.entries()) {
    const dt = t - k.t;
    if (dt < 0 || dt > 0.6) continue;
    const r = (10 + 30 * ease.rise(dt / 0.6)) * scale;
    parts.push(<div key={i} style={{ position: "absolute", left: k.x - r, top: k.y - r, width: 2 * r, height: 2 * r, borderRadius: "50%", background: `color-mix(in srgb, ${tl.brand.accent} 26%, transparent)`, opacity: 1 - dt / 0.6 }} />);
  }
  if (c && c.opacity > 0) {
    const near = tl.clicks.map((k) => t - k.t).find((d) => d > -0.06 && d < 0.16);
    const press = near === undefined ? 1 : 1 - 0.16 * Math.sin(Math.PI * clamp((near + 0.06) / 0.22));
    parts.push(
      <svg key="cursor" width="30" height="30" viewBox="0 0 30 30" style={{ position: "absolute", left: 0, top: 0, opacity: c.opacity, transformOrigin: "4px 3px", transform: `translate(${c.x - 4}px, ${c.y - 3}px) scale(${press * scale})`, filter: "drop-shadow(0 3px 5px rgba(0,0,0,0.3))" }}>
        <path d="M4 3 L4 24.5 L9.4 19.4 L13 27.6 L17 25.9 L13.4 17.8 L20.8 17.8 Z" fill="#111" stroke="#fff" strokeWidth="1.8" strokeLinejoin="round" />
      </svg>,
    );
  }
  return <>{parts}</>;
};

const glassStyle = (th: Theme): CSSProperties => ({
  background: th.glass,
  backdropFilter: "blur(22px) saturate(170%)",
  boxShadow: `0 18px 44px -14px rgba(0,0,0,0.3), 0 0 0 0.5px ${th.hairline}`,
  color: th.ink,
});

const Note = ({ tl, t, th }: { tl: Timeline; t: number; th: Theme }) => {
  const n = tl.notes.find((x) => t >= x.t0 && t <= x.t1);
  if (!n) return null;
  const p = ramp(t, n.t0, n.t0 + 0.55, ease.rise);
  const o = Math.min(p, 1 - ramp(t, n.t1 - 0.3, n.t1));
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 58, display: "flex", justifyContent: "center", opacity: o, transform: `translateY(${(1 - p) * 16}px)` }}>
      <div style={{ ...glassStyle(th), padding: "17px 30px", borderRadius: 22, fontSize: 28, fontWeight: 500, letterSpacing: "-0.014em" }}>{n.text}</div>
    </div>
  );
};

const KEY_SIGNS: Record<string, string> = { Meta: "⌘", Control: "⌃", Alt: "⌥", Shift: "⇧", Enter: "↩", Tab: "⇥", Escape: "esc", Backspace: "⌫", ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→" };
const Keycap = ({ tl, t, th }: { tl: Timeline; t: number; th: Theme }) => {
  const k = tl.keys.find((x) => t >= x.t0 && t <= x.t1);
  if (!k) return null;
  const p = ramp(t, k.t0, k.t0 + 0.3, ease.rise);
  const o = Math.min(p, 1 - ramp(t, k.t1 - 0.25, k.t1));
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 150, display: "flex", justifyContent: "center", gap: 10, opacity: o, transform: `scale(${0.94 + 0.06 * p})` }}>
      {k.label.split("+").map((part) => (
        <div key={part} style={{ ...glassStyle(th), minWidth: 76, height: 76, padding: "0 20px", borderRadius: 16, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 34, fontWeight: 500 }}>{KEY_SIGNS[part] ?? part}</div>
      ))}
    </div>
  );
};

const CENTRE_Y = 400;

const Brandline = ({ headline, accent, sub, cta, tl, t, at, th }: { headline: string; accent?: string; sub?: string; cta?: string; tl: Timeline; t: number; at: number; th: Theme }) => {
  const count = (headline + " " + (accent ?? "")).trim().split(/\s+/).length;
  const subAt = at + 0.35 + count * 0.07;
  return (
    <div style={{ position: "absolute", left: 120, right: 120, top: CENTRE_Y + 130, textAlign: "center" }}>
      <div style={{ fontSize: 92, fontWeight: 600, letterSpacing: "-0.03em", lineHeight: 1.06, color: th.ink }}>
        <Words text={headline} accent={accent} t={t} at={at} color={tl.brand.accent} />
      </div>
      {sub && <div style={{ fontSize: 32, fontWeight: 400, letterSpacing: "-0.012em", color: th.muted, marginTop: 20, opacity: ramp(t, subAt, subAt + 0.7), transform: `translateY(${(1 - ramp(t, subAt, subAt + 0.8, ease.rise)) * 12}px)` }}>{sub}</div>}
      {cta && <div style={{ display: "inline-block", marginTop: 34, padding: "14px 30px", borderRadius: 999, background: tl.brand.accent, color: "#fff", fontSize: 25, fontWeight: 500, opacity: ramp(t, subAt + 0.45, subAt + 1), transform: `translateY(${(1 - ramp(t, subAt + 0.45, subAt + 1.05, ease.rise)) * 12}px)` }}>{cta}</div>}
    </div>
  );
};

export const Film = ({ tl }: { tl: Timeline }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const [fontHold] = useState(() => {
    const handle = delayRender("Loading fonts");
    Promise.all([document.fonts.load('600 60px "Inter Variable"'), document.fonts.load('400 25px "Inter Variable"')]).then(() => continueRender(handle), cancelRender);
    return handle;
  });
  void fontHold;
  const t = frame / fps;
  const th = themes[tl.brand.theme] ?? themes.light;
  const view = cameraAt(tl, t);
  const { intro, outro } = tl;

  // Intro and outro: the logo opens into the app and the app closes back into the logo.
  const diveStart = intro.t1 - intro.dive;
  const dive = ramp(t, diveStart, intro.t1, ease.in);
  const collapse = ramp(t, outro.t0 - 0.05, outro.t0 + outro.collapse, ease.camera);
  const R = 1250;
  const radius = t < intro.t1 ? 90 + (R - 90) * dive : t > outro.t0 ? R * (1 - collapse) : R;
  const worldVisible = radius > 0.5 && t >= diveStart;
  const push = t < intro.t1 + 0.7 ? 1.12 - 0.12 * ramp(t, diveStart, intro.t1 + 0.7, ease.rise) : t > outro.t0 ? 1 - 0.05 * collapse : 1;
  const clip = t < intro.t1 || t > outro.t0 ? `circle(${radius}px at 960px ${CENTRE_Y}px)` : undefined;

  const float = Math.sin(t * 1.25) * 7;
  const logoIn = ramp(t, 0.1, 1.2, ease.rise);
  // The sphere is a lens the app opens inside. A picture logo can't be seen through, so it steps aside early.
  const lens = !tl.brand.logo;
  const introLogoScale = (0.72 + 0.28 * logoIn) * (1 + (lens ? 11 : 0.5) * ramp(t, diveStart, intro.t1, ease.in));
  const introLogoOpacity = logoIn * (1 - (lens ? ramp(t, diveStart + 0.25, intro.t1 - 0.25) : ramp(t, diveStart - 0.2, diveStart + 0.35)));
  const introTextOpacity = 1 - ramp(t, diveStart - 0.35, diveStart + 0.15);
  const outroAt = outro.t0 + outro.collapse - 0.5;
  const outroLogo = ramp(t, outroAt, outroAt + 1.0, ease.rise);
  const endFade = 1 - ramp(t, tl.duration - 1.1, tl.duration - 0.15);

  return (
    <AbsoluteFill style={{ background: th.bg, fontFamily: `${tl.brand.font ?? "'Inter Variable'"}, -apple-system, "Helvetica Neue", "PingFang SC", "Hiragino Sans", "Apple SD Gothic Neo", "Geeza Pro", sans-serif`, fontOpticalSizing: "auto", color: th.ink, overflow: "hidden" }}>
      <AbsoluteFill style={{ background: `radial-gradient(1500px 880px at 50% -6%, ${th.glow}, transparent 72%)` }} />
      {worldVisible && (
        <AbsoluteFill style={{ clipPath: clip }}>
          <AbsoluteFill style={{ background: th.bg }} />
          <AbsoluteFill style={{ background: `radial-gradient(1500px 880px at 50% -6%, ${th.glow}, transparent 72%)` }} />
          <div style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, transformOrigin: "0 0", transform: `scale(${push}) translate(${(960 / push - 960) * 1}px, ${(540 / push - 540) * 1}px) translate(${960 - view.cx * view.z}px, ${540 - view.cy * view.z}px) scale(${view.z})` }}>
            <SceneTitle tl={tl} t={t} th={th} z={view.z} />
            <AppWindow tl={tl} t={t} th={th} />
            <Pointer tl={tl} t={t} z={view.z} />
          </div>
          <Note tl={tl} t={t} th={th} />
          <Keycap tl={tl} t={t} th={th} />
        </AbsoluteFill>
      )}

      {t < intro.t1 && (
        <>
          <Logo tl={tl} size={180} style={{ position: "absolute", left: 960 - 90, top: CENTRE_Y - 90 + float * (1 - dive), opacity: introLogoOpacity, transform: `scale(${introLogoScale})` }} />
          <div style={{ opacity: introTextOpacity }}>
            <Brandline headline={intro.headline} accent={intro.accent} sub={intro.sub} tl={tl} t={t} at={0.9} th={th} />
          </div>
        </>
      )}

      {t > outroAt && (
        <AbsoluteFill style={{ opacity: endFade }}>
          <Logo tl={tl} size={150} style={{ position: "absolute", left: 960 - 75, top: CENTRE_Y - 75 + float * outroLogo * 0.7, opacity: outroLogo, transform: `scale(${0.8 + 0.2 * outroLogo})` }} />
          <Brandline headline={outro.headline} accent={outro.accent} sub={outro.sub} cta={outro.cta} tl={tl} t={t} at={outroAt + 0.3} th={th} />
        </AbsoluteFill>
      )}

      <AbsoluteFill style={{ background: th.bg, opacity: 1 - ramp(t, 0, 0.5) }} />
      <Audio src={staticFile(tl.audio.music)} volume={tl.audio.musicGain} />
      <Audio src={staticFile(tl.audio.sfx)} volume={1} />
    </AbsoluteFill>
  );
};
