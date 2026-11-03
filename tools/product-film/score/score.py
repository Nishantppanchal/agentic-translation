#!/usr/bin/env python3
"""An original score for the film, synthesised from timeline.json (no samples, so nothing to license).

    score.py <timeline.json> <output dir>

Writes music.wav (unless the storyboard brings its own track) and sfx.wav. The timeline says, bar by bar, how much
energy the film wants; every scene starts on a downbeat, so changes in the music land on changes in the picture.

Two moods:
  airy   felt-piano pulse, warm pad, soft kick. The default: clean and unobtrusive, like a keynote demo.
  pulse  the same harmony with more drive: firmer kick, claps, hats, a bell arpeggio up front.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pyloudnorm
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt, sosfilt_zi

SR = 44100
TARGET_LUFS = -18.0  # a bed under a picture, not a song
PEAK = 10 ** (-2.0 / 20)

# IV – I/3 – vi – V: open and rising, never resolving too hard. MIDI notes in C, moved to the storyboard's key.
CHORDS = [
    [53, 60, 64, 67, 69],  # Fmaj9-ish
    [52, 55, 60, 67, 74],  # C/E add 9
    [57, 60, 64, 67, 71],  # Am9
    [55, 62, 67, 69, 72],  # G sus
]
ROOTS = [41, 40, 45, 43]
BELLS = [
    [77, 84, 81, 88, 86, 84, 81, 84],
    [76, 83, 79, 86, 88, 83, 79, 83],
    [76, 84, 79, 86, 83, 84, 79, 83],
    [74, 83, 79, 86, 84, 83, 79, 81],
]
MELODY = [  # bar in the 4-bar cycle, beat, note, beats
    (0, 0, 81, 1.5), (0, 1.5, 79, 0.5), (0, 2, 84, 2),
    (1, 0, 83, 1.5), (1, 1.5, 79, 0.5), (1, 2, 76, 2),
    (2, 0, 76, 1), (2, 1, 79, 1), (2, 2, 83, 2),
    (3, 0, 81, 3), (3, 3, 79, 1),
]
# Which layers play at each energy, and how loud. Filter is the pad's brightness in Hz.
ENERGY = {
    "intro": dict(pad=0.85, cut=620, felt=0.0, sparse=0.7, bell=0.0, sub=0.0, kick=0.0, shaker=0.0, melody=0.0),
    "low": dict(pad=0.8, cut=950, felt=0.55, sparse=0.0, bell=0.0, sub=0.6, kick=0.0, shaker=0.0, melody=0.0),
    "mid": dict(pad=0.8, cut=1300, felt=0.7, sparse=0.0, bell=0.35, sub=0.8, kick=0.5, shaker=0.35, melody=0.0),
    "breath": dict(pad=0.95, cut=800, felt=0.0, sparse=0.85, bell=0.3, sub=0.3, kick=0.0, shaker=0.0, melody=0.0),
    "high": dict(pad=0.85, cut=1750, felt=0.85, sparse=0.0, bell=0.55, sub=1.0, kick=0.85, shaker=0.7, melody=0.8),
    "build": dict(pad=0.9, cut=2300, felt=0.9, sparse=0.0, bell=0.7, sub=1.0, kick=0.85, shaker=0.9, melody=0.0),
    "outro": dict(pad=0.95, cut=1000, felt=0.0, sparse=0.8, bell=0.25, sub=0.65, kick=0.0, shaker=0.0, melody=0.45),
}
MOODS = {
    "airy": dict(kick=0.55, clap=0.0, shaker=0.5, bell=0.75, felt=1.0, bloom=0.55),
    "pulse": dict(kick=1.0, clap=0.42, shaker=0.95, bell=1.15, felt=0.8, bloom=0.95),
}
FELT_PATTERN = [(0, 1.0), (1.5, 0.75), (3, 0.85), (4, 0.6), (5.5, 0.72), (7, 0.55)]  # in eighths: 3+3+2

rng = np.random.default_rng(7)


def midi(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def lowpass(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def highpass(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bandpass(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def saw(freq, n, phase=0.0):
    """Band-limited (PolyBLEP) sawtooth."""
    dt = freq / SR
    ph = (phase + np.arange(n) * dt) % 1.0
    y = 2 * ph - 1
    m = ph < dt
    x = ph[m] / dt
    y[m] -= x + x - x * x - 1
    m = ph > 1 - dt
    x = (ph[m] - 1) / dt
    y[m] -= x * x + x + x + 1
    return y


def place(buf, start, sig, gain=1.0):
    i = int(round(start * SR))
    if i >= len(buf) or i + len(sig) <= 0:
        return
    if i < 0:
        sig, i = sig[-i:], 0
    j = min(len(buf), i + len(sig))
    buf[i:j] += gain * sig[: j - i]


def envelope(n, attack, decay, sustain, release, hold):
    t = np.arange(n) / SR
    e = np.where(t < attack, t / max(attack, 1e-4), sustain + (1 - sustain) * np.exp(-(t - attack) / max(decay, 1e-4)))
    late = t > hold
    e[late] *= np.exp(-(t[late] - hold) / max(release, 1e-4))
    return e


_felt_cache = {}


def felt(note, length=1.6):
    """A felted piano: a soft hammer thump, a few inharmonic partials that die off quickly, the top rolled away."""
    key = (note, length)
    if key in _felt_cache:
        return _felt_cache[key]
    f = midi(note)
    n = int(length * SR)
    t = np.arange(n) / SR
    y = np.zeros(n)
    for k, (amp, tau) in enumerate([(1.0, 0.55), (0.42, 0.34), (0.2, 0.2), (0.09, 0.12), (0.04, 0.08)], start=1):
        stretched = k * (1 + 0.00035 * k * k)
        y += amp * np.sin(2 * np.pi * f * stretched * t) * np.exp(-t / tau)
    thump = lowpass(rng.standard_normal(n), 1100) * np.exp(-t / 0.012) * 0.12
    y = (y + thump) * np.minimum(1, t / 0.004)
    y = lowpass(y, min(4200, f * 7))
    _felt_cache[key] = y
    return y


def bell(f, length=1.0):
    n = int(length * SR)
    t = np.arange(n) / SR
    mod = np.sin(2 * np.pi * f * 3.5 * t) * 0.9 * np.exp(-t / 0.14)
    y = np.sin(2 * np.pi * f * t + mod) * np.exp(-t / 0.4)
    return y * np.minimum(1, t / 0.003)


def kick(body=0.2):
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    pitch = 46 + 80 * np.exp(-t / 0.03)
    tone = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-t / body)
    return np.tanh(1.3 * tone)


def clap():
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    e = sum(np.where(t >= off, np.exp(-(t - off) / tau), 0) for off, tau in [(0, 0.006), (0.011, 0.006), (0.022, 0.12)])
    return bandpass(rng.standard_normal(n), 900, 3800) * e * 0.5


def shaker():
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    return highpass(rng.standard_normal(n), 6500, 4) * np.minimum(1, t / 0.008) * np.exp(-t / 0.016) * 0.35


def bloom():
    """A soft arrival: a reversed swell into the downbeat and a low, round thud on it. Returns (swell, thud)."""
    n = int(2.2 * SR)
    t = np.arange(n) / SR
    swell = lowpass(rng.standard_normal(n), 2400) * (t / t[-1]) ** 3
    swell += sum(np.sin(2 * np.pi * midi(m) * t) for m in (72, 79, 84)) * 0.05 * (t / t[-1]) ** 2.4
    m = int(2.4 * SR)
    u = np.arange(m) / SR
    thud = np.sin(2 * np.pi * np.cumsum(40 + 34 * np.exp(-u / 0.07)) / SR) * np.exp(-u / 0.8)
    return swell, thud


def tick():
    n = int(0.04 * SR)
    t = np.arange(n) / SR
    return highpass(rng.standard_normal(n), 2600) * np.exp(-t / 0.0035) * 0.5 + np.sin(2 * np.pi * 1500 * t) * np.exp(-t / 0.007) * 0.35


def air():
    n = int(1.1 * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    out = np.zeros(n)
    for s0 in range(0, n, 1024):
        s1 = min(n, s0 + 1024)
        fc = 400 + 2400 * np.sin(np.pi * s0 / n)
        out[s0:s1] = bandpass(x[max(0, s0 - 512) : s1], fc * 0.7, fc * 1.4)[-(s1 - s0) :]
    return out * np.sin(np.pi * t / t[-1]) ** 2


def reverb(left, right, seconds=2.6, tail=0.72):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = []
    for sig in (left, right):
        ir = lowpass(rng.standard_normal(n) * np.exp(-t / tail), 5500)
        ir /= np.sqrt(np.sum(ir**2))
        out.append(fftconvolve(highpass(sig, 220), ir)[: len(sig)])
    return out


def write_wav(path, stereo):
    wavfile.write(path, SR, (np.clip(stereo, -1, 1) * 32767).astype(np.int16))


def compose(tl):
    bpm, bar, arrangement = tl["bpm"], tl["bar"], tl["arrangement"]
    beat = bar / 4
    bars = len(arrangement)
    music = tl["music"]
    mood = MOODS.get(music.get("mood", "airy"))
    if mood is None:
        raise SystemExit(f"Unknown mood {music.get('mood')!r}. Moods: {', '.join(MOODS)}.")
    shift = int(music.get("key", 2))  # semitones up from C: D major by default
    N = int(tl["duration"] * SR) + 1
    layers = {k: np.zeros((2, N)) for k in ("pad", "felt", "bell", "melody", "sub", "drums", "fx")}
    send = np.zeros((2, N))
    kicks = []

    def table(b):
        return ENERGY[arrangement[min(b, bars - 1)]]

    # Pad: detuned saws through a filter that opens with the energy.
    raw = np.zeros((2, N))
    for b in range(bars):
        last = b == bars - 1
        chord = CHORDS[0] if last else CHORDS[b % 4]
        start = b * bar
        hold = bar + (tl["duration"] - bars * bar if last else 0)
        n = int((hold + 1.4) * SR)
        env = envelope(n, 2.2 if b == 0 else 0.45, 1.5, 0.85, 0.9, hold)
        for note in chord:
            f = midi(note + shift)
            for cents in (-7, 0, 7):
                ph = rng.random()
                w = 1.0 if cents == 0 else 0.65
                place(raw[0], start, saw(f * 2 ** ((cents + 1.5) / 1200), n, ph) * env, w)
                place(raw[1], start, saw(f * 2 ** ((-cents - 1.5) / 1200), n, 1 - ph) * env, w)
    # Cutoff and level glide smoothly from bar to bar.
    t_all = np.arange(N) / SR
    idx = np.minimum((t_all / bar).astype(int), bars - 1)
    cut = np.array([table(b)["cut"] for b in range(bars)], float)[idx]
    level = np.array([table(b)["pad"] for b in range(bars)], float)[idx]
    width = int(0.9 * SR)
    kernel = np.ones(width) / width
    cut = fftconvolve(np.pad(cut, width, mode="edge"), kernel, mode="same")[width:-width]
    level = fftconvolve(np.pad(level, width, mode="edge"), kernel, mode="same")[width:-width]
    block = 2048
    for ch in range(2):
        z = None
        for s0 in range(0, N, block):
            s1 = min(N, s0 + block)
            sos = butter(2, float(np.clip(cut[s0], 200, 9000)), "low", fs=SR, output="sos")
            if z is None:
                z = sosfilt_zi(sos) * 0
            layers["pad"][ch, s0:s1], z = sosfilt(sos, raw[ch, s0:s1], zi=z)
    layers["pad"] *= 0.022 * level

    # Felt piano: the pulse, or single rolled chords when the film is quiet.
    for b in range(bars):
        e = table(b)
        chord = CHORDS[b % 4]
        b0 = b * bar
        if e["felt"]:
            tones = sorted(chord)[1:]
            for k, (eighth, vel) in enumerate(FELT_PATTERN):
                note = tones[(k * 2) % len(tones)] + 12 * (k % 3 == 2)
                y = felt(note + shift)
                pan = 0.5 + 0.2 * np.sin(k * 2.1 + b)
                at = b0 + eighth * beat / 2
                g = 0.13 * e["felt"] * vel * mood["felt"]
                place(layers["felt"][0], at, y, g * (1 - pan) * 1.4)
                place(layers["felt"][1], at, y, g * pan * 1.4)
        if e["sparse"]:
            for k, note in enumerate(sorted(chord)[1:]):
                y = felt(note + shift + 12, 2.4)
                at = b0 + k * 0.09 + (0 if b % 2 == 0 else beat)
                place(layers["felt"][0], at, y, 0.1 * e["sparse"] * (0.7 + 0.1 * k))
                place(layers["felt"][1], at + 0.006, y, 0.1 * e["sparse"] * (1.1 - 0.1 * k))

    # Bell arpeggio with a dotted-eighth echo.
    arp = np.zeros((2, N))
    for b in range(bars):
        e = table(b)
        if not e["bell"]:
            continue
        fig = BELLS[b % 4]
        for s, note in enumerate(fig):
            if s % 2 and e["bell"] < 0.5:
                continue
            pan = 0.5 + 0.34 * np.sin(s * 1.7 + b)
            y = bell(midi(note + shift))
            g = 0.05 * e["bell"] * mood["bell"]
            place(arp[0], b * bar + s * bar / 8, y, g * (1 - pan) * 1.5)
            place(arp[1], b * bar + s * bar / 8, y, g * pan * 1.5)
    delay = int(0.75 * beat * SR)
    echoes = np.zeros_like(arp)
    for k in range(1, 6):
        g = 0.36**k
        sh = delay * k
        if sh >= N:
            break
        echoes[k % 2, sh:] += g * arp[1 - k % 2, : N - sh]
    layers["bell"] = arp + np.array([lowpass(echoes[0], 3800), lowpass(echoes[1], 3800)]) * 0.8

    # The tune, only where the film is at full stretch.
    for b in range(bars):
        amt = table(b)["melody"]
        if not amt:
            continue
        for cycle, at_beat, note, beats in MELODY:
            if cycle != b % 4:
                continue
            n = int((beats * beat + 0.8) * SR)
            t = np.arange(n) / SR
            vibrato = 1 + 0.003 * np.sin(2 * np.pi * 5 * t) * np.minimum(1, t / 0.5)
            ph = 2 * np.pi * np.cumsum(midi(note + shift) * vibrato) / SR
            y = (np.sin(ph) + 0.16 * np.sin(2 * ph) + 0.05 * np.sin(3 * ph)) * envelope(n, 0.05, 0.6, 0.65, 0.35, beats * beat)
            for ch in range(2):
                place(layers["melody"][ch], b * bar + at_beat * beat, y, 0.055 * amt)

    # Sub bass, kick, shaker, clap.
    K = kick(0.2)
    C = clap()
    S = shaker()
    for b in range(bars):
        e = table(b)
        b0 = b * bar
        if e["sub"]:
            f = midi(ROOTS[b % 4] - 12 + shift)
            pattern = [(0, 3.5), (3.5, 0.5)] if e["kick"] else [(0, 4)]
            for at_beat, beats in pattern:
                n = int((beats * beat + 0.2) * SR)
                t = np.arange(n) / SR
                y = np.tanh(1.2 * (np.sin(2 * np.pi * f * t) + 0.2 * np.sin(4 * np.pi * f * t))) * envelope(n, 0.012, 0.4, 0.7, 0.08, beats * beat - 0.05)
                for ch in range(2):
                    place(layers["sub"][ch], b0 + at_beat * beat, y, 0.2 * e["sub"])
        if e["kick"]:
            hits = range(4) if e["kick"] > 0.7 else (0, 2)
            for h in hits:
                at = b0 + h * beat
                kicks.append(at)
                g = 0.42 * e["kick"] * mood["kick"]
                place(layers["drums"][0], at, K, g)
                place(layers["drums"][1], at, K, g)
            if mood["clap"]:
                for h in (1, 3):
                    place(layers["drums"][0], b0 + h * beat, C, mood["clap"] * e["kick"] * 0.55)
                    place(layers["drums"][1], b0 + h * beat, C, mood["clap"] * e["kick"] * 0.5)
                    place(send[1], b0 + h * beat, C, mood["clap"] * 0.12)
        if e["shaker"]:
            for s in range(8):
                g = e["shaker"] * mood["shaker"] * (0.32 if s % 2 else 0.14)
                pan = 0.35 + 0.3 * ((s * 7) % 5) / 4
                place(layers["drums"][0], b0 + s * beat / 2, S, g * (1 - pan) * 1.2)
                place(layers["drums"][1], b0 + s * beat / 2, S, g * pan * 1.2)

    # The sub and pad breathe with the kick.
    duck = np.ones(N)
    for at in kicks:
        i = int(at * SR)
        j = min(N, i + int(0.3 * SR))
        tt = np.arange(j - i) / SR
        depth = 0.4 * mood["kick"]
        duck[i:j] = np.minimum(duck[i:j], 1 - depth * np.exp(-tt / 0.1))

    # An arrival when the app first appears, and again when the film comes home.
    swell, thud = bloom()
    arrivals = []
    if "intro" in arrangement:
        arrivals.append(arrangement.index("intro") + arrangement.count("intro"))
    if "outro" in arrangement:
        arrivals.append(arrangement.index("outro"))
    for b in arrivals:
        if b >= bars:
            continue
        at = b * bar
        for ch in range(2):
            place(layers["fx"][ch], at - len(swell) / SR, swell, 0.075 * mood["bloom"])
            place(layers["fx"][ch], at, thud, 0.24 * mood["bloom"])
            place(send[ch], at - len(swell) / SR, swell, 0.05)

    # A very quiet shimmer under the opening.
    if arrangement and arrangement[0] == "intro":
        n = int(min(arrangement.count("intro") * bar + 1, tl["duration"]) * SR)
        t = np.arange(n) / SR
        sh = sum(np.sin(2 * np.pi * midi(m + shift) * t + rng.random() * 6) for m in (84, 91, 96)) * 0.25
        sh *= np.minimum(1, t / 3) * (0.55 + 0.45 * np.sin(2 * np.pi * 0.2 * t)) * np.minimum(1, (t[-1] - t) / 1.0)
        place(layers["fx"][0], 0, sh, 0.018)
        place(layers["fx"][1], 0.013, sh, 0.018)

    # Mix.
    send += layers["pad"] * 0.45 + layers["felt"] * 0.42 + layers["bell"] * 0.55 + layers["melody"] * 0.6
    room = reverb(send[0], send[1])
    mix = np.zeros((2, N))
    for name, gain in [("pad", 1), ("sub", 1), ("felt", 1), ("bell", 1), ("melody", 0.85), ("drums", 1), ("fx", 1)]:
        layer = layers[name] * gain
        mix += layer * duck if name in ("pad", "sub") else layer
    mix += np.array(room) * 0.5
    mix = highpass(mix, 30).T

    # Level to the target, then round off any peaks.
    mix = mix * 10 ** ((TARGET_LUFS - pyloudnorm.Meter(SR).integrated_loudness(mix)) / 20)
    peak = float(np.max(np.abs(mix)))
    if peak > PEAK:
        ceil = PEAK
        drive = np.abs(mix) > 0.7 * ceil
        mix[drive] = np.sign(mix[drive]) * (0.7 * ceil + 0.3 * ceil * np.tanh((np.abs(mix[drive]) - 0.7 * ceil) / (0.3 * ceil)))
    fade = np.ones(N)
    tail = int(min(2.2, tl["duration"] / 4) * SR)
    fade[-tail:] = np.linspace(1, 0, tail) ** 2
    fade[: int(0.02 * SR)] = np.linspace(0, 1, int(0.02 * SR))
    return mix * fade[:, None]


def effects(tl):
    N = int(tl["duration"] * SR) + 1
    out = np.zeros((2, N))
    T, A = tick(), air()
    cues = tl["cues"]
    for at in cues.get("click", []):
        for ch in range(2):
            place(out[ch], at, T, 0.11)
    for i, at in enumerate(cues.get("key", [])):
        y = lowpass(T, 3200 + 900 * (i % 3))
        place(out[0], at, y, 0.028 + 0.006 * (i % 2))
        place(out[1], at, y, 0.03)
    for at in cues.get("scene", []):
        place(out[0], at - 0.5, A, 0.018)
        place(out[1], at - 0.48, A, 0.018)
    return out.T


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    tl = json.loads(Path(sys.argv[1]).read_text())
    outdir = Path(sys.argv[2])
    write_wav(outdir / "sfx.wav", effects(tl))
    if tl["music"].get("file"):
        print("  Using your track; sound effects written.")
        return
    mix = compose(tl)
    write_wav(outdir / "music.wav", mix)
    meter = pyloudnorm.Meter(SR)
    print(f"  {tl['duration']:.1f}s, mood {tl['music'].get('mood', 'airy')}, {meter.integrated_loudness(mix):.1f} LUFS, peak {20 * np.log10(np.max(np.abs(mix))):.1f} dBFS")


if __name__ == "__main__":
    main()
