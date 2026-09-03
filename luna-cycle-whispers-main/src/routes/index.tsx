import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { NovaraLogo } from "@/components/NovaraLogo";
import { WearableRing } from "@/components/WearableRing";
import {
  AreaChart, Area, ResponsiveContainer, Tooltip, XAxis, YAxis,
  LineChart, Line,
} from "recharts";
import {
  Activity, Fingerprint, Cpu, Battery, Layers, Shield,
  Radio, Heart, Thermometer, Zap, Eye, FlaskConical,
  ArrowRight, ChevronDown, Check, Sparkles, RefreshCw, Feather
} from "lucide-react";
import { LivePulseSimulator } from "@/components/LivePulseSimulator";
import { useTheme } from "@/context/ThemeContext";
import { useEffect, useRef, useState } from "react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Novara — Continuous Physiological Sensing" },
      { name: "description", content: "A next-generation physiological sensing platform. Understand your body's unique baseline through continuous, high-quality wearable sensing." },
    ],
  }),
  component: LandingPage,
});

/* ═══════════════════════════════════════════
   SYNTHETIC DATA FOR CHARTS
   ═══════════════════════════════════════════ */

// PPG optical waveform
const ppgData = Array.from({ length: 80 }, (_, i) => {
  const t = i / 80;
  const beat = Math.sin(t * Math.PI * 10);
  const systolic = Math.pow(Math.max(0, beat), 2.5) * 85;
  const dicrotic = Math.pow(Math.max(0, Math.sin(t * Math.PI * 10 + 1.2)), 4) * 20;
  return { t: i, v: 30 + systolic + dicrotic + Math.random() * 3 };
});

// Single-lead ECG trace
const ecgData = Array.from({ length: 100 }, (_, i) => {
  const mod = i % 25;
  let v = 20;
  if (mod === 5) v = 24; // P wave
  else if (mod === 8) v = 10; // Q wave
  else if (mod === 10) v = 95; // R peak
  else if (mod === 12) v = 5;  // S wave
  else if (mod === 16) v = 32; // T wave
  return { t: i, ecg: v + Math.random() * 2 };
});

// Heart rate trend — 24h
const hrData = Array.from({ length: 24 }, (_, i) => {
  const base = i < 6 ? 58 : i < 8 ? 62 : i < 12 ? 72 : i < 14 ? 68 : i < 18 ? 75 : i < 21 ? 70 : 62;
  return { h: `${i}:00`, bpm: base + Math.floor(Math.random() * 6 - 3) };
});

// HRV sparkline
const hrvSpark = [
  { v: 52 }, { v: 58 }, { v: 55 }, { v: 61 }, { v: 57 }, { v: 63 }, { v: 60 },
  { v: 56 }, { v: 62 }, { v: 59 }, { v: 65 }, { v: 61 }, { v: 58 },
];

// Signal quality comparison
const signalQuality = [
  { t: "Wrist Wearable", snr: 42 },
  { t: "Forearm Strap", snr: 51 },
  { t: "Ear Clip", snr: 62 },
  { t: "Novara Finger PPG", snr: 88 },
];

// Motion artifact data
const motionData = Array.from({ length: 40 }, (_, i) => {
  const motion = i > 12 && i < 28 ? Math.sin((i - 12) * 0.4) * 15 + Math.random() * 8 : Math.random() * 2;
  const signal = 60 + Math.sin(i * 0.8) * 12 + Math.random() * 3;
  return { t: i, signal: Math.round(signal), motion: Math.round(motion) };
});

// Temperature trend
const tempData = Array.from({ length: 24 }, (_, i) => {
  const base = i < 6 ? 36.2 : i < 12 ? 36.4 : i < 18 ? 36.6 : 36.3;
  return { h: `${i}h`, temp: +(base + Math.random() * 0.3).toFixed(1) };
});

// Weekly baseline
const weekBaseline = [
  { d: "Mon", score: 72 }, { d: "Tue", score: 75 }, { d: "Wed", score: 68 },
  { d: "Thu", score: 74 }, { d: "Fri", score: 71 }, { d: "Sat", score: 78 }, { d: "Sun", score: 76 },
];


/* ═══════════════════════════════════════════
   MAIN LANDING PAGE
   ═══════════════════════════════════════════ */

function LandingPage() {
  const { mode } = useTheme();
  const sectionsRef = useRef<HTMLDivElement>(null);
  const [activeEcgMode, setActiveEcgMode] = useState<"bra" | "wrist">("bra");

  // Theme-aware palette
  const t = mode === "day" ? {
    chartStroke1: "#C0846D",
    chartStroke2: "#8A7E72",
    chartStroke3: "#D4A98A",
    chartFillTop: "rgba(192, 132, 109, 0.22)",
    chartFillBot: "rgba(192, 132, 109, 0.0)",
    accentGlow: "rgba(192, 132, 109, 0.15)",
    novaraColor: "#C0846D",
    wristColor: "#B0A090",
  } : {
    chartStroke1: "#4FD1C5",
    chartStroke2: "#63B3ED",
    chartStroke3: "#81E6D9",
    chartFillTop: "rgba(79, 209, 197, 0.22)",
    chartFillBot: "rgba(79, 209, 197, 0.0)",
    accentGlow: "rgba(79, 209, 197, 0.08)",
    novaraColor: "#4FD1C5",
    wristColor: "#6B97A8",
  };

  // Scroll reveal observer
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("revealed");
          }
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -40px 0px" }
    );

    const els = document.querySelectorAll(".reveal-on-scroll");
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return (
    <Layout>
      <div ref={sectionsRef}>

        {/* ═══════════════════════════════════════
           1. HERO
           ═══════════════════════════════════════ */}
        <section className="landing-section flex flex-col items-center text-center" style={{ paddingTop: 40, paddingBottom: 40 }}>
          <div className="fade-in-up">
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border mb-6 text-xs font-medium tracking-wide"
              style={{
                borderColor: "var(--border-subtle)",
                background: "var(--glass-bg)",
                color: "var(--accent-primary)",
              }}
            >
              <NovaraLogo className="w-3.5 h-3.5" />
              <span>Smart Physiology Monitoring · Naturally. Continuously.</span>
            </div>

            <h1 className="max-w-4xl mx-auto tracking-tight font-display font-normal text-balance">
              Understand your body's unique rhythm.
            </h1>
            <p className="section-subtitle mx-auto mt-6 text-balance">
              Novara is a next-generation physiological sensing platform. Engineered with an ultra-light
              3D-knit hand wearable for index-finger optical PPG, and a companion ECG strap for clinical-grade heart monitoring.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mt-8 relative z-20">
              <a
                href="#technology"
                className="btn-primary flex items-center gap-3 text-base px-8 py-3.5 cursor-pointer"
                onClick={(e) => {
                  e.preventDefault();
                  document.querySelector("#technology")?.scrollIntoView({ behavior: "smooth" });
                }}
              >
                Explore Technology <ArrowRight size={16} strokeWidth={1.5} />
              </a>
              <a
                href="#design"
                className="btn-glass flex items-center gap-3 text-base px-8 py-3.5 cursor-pointer"
                onClick={(e) => {
                  e.preventDefault();
                  document.querySelector("#design")?.scrollIntoView({ behavior: "smooth" });
                }}
              >
                See the Design <ChevronDown size={16} strokeWidth={1.5} />
              </a>
            </div>
          </div>

          {/* Hero Visual — Official Render Showcase & Animated Sensing Ring */}
          <div className="mt-12 w-full max-w-5xl relative fade-in-up" style={{ animationDelay: "0.2s" }}>
            <GlassCard className="p-4 md:p-6 overflow-hidden group" hover={false}>
              <div className="flex flex-col lg:flex-row items-center justify-between gap-6 bg-black/20 p-4 md:p-6 rounded-2xl border" style={{ borderColor: "var(--border-subtle)" }}>
                
                {/* Official Render Showcase (Uncropped Fitting) */}
                <div className="flex-1 relative w-full flex items-center justify-center min-h-[420px] md:min-h-[520px]">
                  <img
                    src="/images/hero-render.png"
                    alt="Novara Hand Wearable Render"
                    className="w-full h-auto max-h-[580px] object-contain rounded-xl shadow-2xl transition-transform duration-700 group-hover:scale-[1.01]"
                  />

                  {/* Floating Hotspot: PPG Sensor */}
                  <div className="absolute top-[6%] left-[4%] md:top-[8%] md:left-[8%] flex items-center gap-3 backdrop-blur-md px-3.5 py-2 rounded-full border shadow-xl animate-bounce"
                    style={{
                      background: "rgba(18, 14, 18, 0.85)",
                      borderColor: "var(--accent-primary)",
                      animationDuration: "4s",
                    }}
                  >
                    <span className="relative flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                    </span>
                    <div className="text-left">
                      <div className="text-[11px] font-semibold text-white tracking-wide">PPG Optical Sensor</div>
                      <div className="text-[9.5px] text-emerald-300 font-mono">Red (660nm) & IR (940nm) LEDs</div>
                    </div>
                  </div>

                  {/* Floating Hotspot: Anatomical 3D Knit */}
                  <div className="absolute top-[46%] right-[2%] md:top-[44%] md:right-[6%] flex items-center gap-3 backdrop-blur-md px-3.5 py-2 rounded-full border shadow-xl"
                    style={{
                      background: "rgba(18, 14, 18, 0.85)",
                      borderColor: "var(--border-subtle)",
                    }}
                  >
                    <Feather size={14} className="text-amber-200" />
                    <div className="text-left">
                      <div className="text-[11px] font-semibold text-white tracking-wide">Ultra-Soft 3D Knit</div>
                      <div className="text-[9.5px] text-stone-300">Anatomical Ulnar Flow Fit</div>
                    </div>
                  </div>

                  {/* Floating Hotspot: Wrist Module Pod */}
                  <div className="absolute bottom-[6%] right-[6%] md:bottom-[8%] md:right-[12%] flex items-center gap-3 backdrop-blur-md px-3.5 py-2 rounded-full border shadow-xl"
                    style={{
                      background: "rgba(18, 14, 18, 0.85)",
                      borderColor: "var(--border-subtle)",
                    }}
                  >
                    <Battery size={14} className="text-cyan-300" />
                    <div className="text-left">
                      <div className="text-[11px] font-semibold text-white tracking-wide">Magnetic Module Pod</div>
                      <div className="text-[9.5px] text-cyan-200 font-mono">3–5 Days Battery · BLE Sync</div>
                    </div>
                  </div>
                </div>

                {/* Animated Sensing Ring Card */}
                <div className="w-full lg:w-72 flex flex-col items-center justify-center p-6 rounded-2xl border bg-black/40 backdrop-blur-md flex-shrink-0" style={{ borderColor: "var(--border-subtle)" }}>
                  <WearableRing size={200} />
                  <div className="text-center mt-4">
                    <div className="text-xs font-semibold text-[var(--accent-primary)] tracking-widest uppercase">Optical Sensing Ring</div>
                    <div className="text-[11px] text-[var(--text-secondary)] mt-1 leading-relaxed">
                      Continuous PPG waveform pulse trace & orbital sensing matrix
                    </div>
                  </div>
                </div>

              </div>
            </GlassCard>
          </div>
        </section>


        {/* ═══════════════════════════════════════
           2. WHAT IS NOVARA & PRODUCT ECOSYSTEM
           ═══════════════════════════════════════ */}
        <section className="landing-section reveal-on-scroll">
          <div className="section-divider mb-16" />
          <div className="max-w-3xl mx-auto text-center mb-16">
            <div className="section-label mb-4">Product System</div>
            <h2>Two Wearables. One Complete Picture.</h2>
            <p className="section-subtitle mx-auto mt-6">
              Rather than simply tracking steps, Novara captures high-fidelity physiological signals directly from your body’s optimal anatomical locations.
            </p>
          </div>

          {/* Dual Wearables Showcase Grid */}
          <div className="grid md:grid-cols-2 gap-8">
            
            {/* Wearable 1: Hand Sensing Platform */}
            <GlassCard className="p-6 md:p-8 flex flex-col justify-between" hover={false}>
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="phase-pill text-xs font-medium">Stage 1 · Core Platform</span>
                  <span className="text-xs font-mono text-[var(--accent-primary)]">Hand Wearable</span>
                </div>

                {/* Fully visible, uncropped image container */}
                <div className="rounded-xl overflow-hidden border mb-6 bg-stone-900/30 dark:bg-black/50 p-2 md:p-4 flex items-center justify-center min-h-[300px] md:min-h-[360px]" style={{ borderColor: "var(--border-subtle)" }}>
                  <img
                    src="/images/device-closeup.png"
                    alt="Novara Hand Wearable Sensor Diagram"
                    className="w-full h-auto max-h-[420px] object-contain rounded-lg shadow-lg"
                  />
                </div>

                <h3 className="text-xl mb-3">Novara Hand Sensing Wearable</h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-6">
                  Follows the natural ulnar contour of the hand to place ultra-low profile optical sensors directly over the palmar digital arteries at the index finger.
                </p>

                <div className="space-y-3 border-t pt-4" style={{ borderColor: "var(--border-subtle)" }}>
                  {[
                    { title: "PPG Optical Sensor", detail: "Dual Red (660nm) & IR (940nm) LEDs for blood flow & HR" },
                    { title: "Skin Temperature", detail: "Precision thermal tracking for metabolic & vascular shifts" },
                    { title: "3-Axis Accelerometer", detail: "Movement, rest quality, posture & activity context" },
                    { title: "Anatomical Ulnar Fit", detail: "Ultra-soft 3D knit fabric designed for 24/7 second-skin wear" },
                    { title: "Magnetic Charging", detail: "3–5 days continuous monitoring on a single charge" },
                  ].map((item) => (
                    <div key={item.title} className="flex items-start gap-3 text-left">
                      <div className="w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5" style={{ background: "var(--nav-active-bg)", color: "var(--accent-primary)" }}>
                        <Check size={12} strokeWidth={2.5} />
                      </div>
                      <div>
                        <div className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{item.title}</div>
                        <div className="text-[11px] text-[var(--text-secondary)]">{item.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </GlassCard>

            {/* Wearable 2: ECG Companion */}
            <GlassCard className="p-6 md:p-8 flex flex-col justify-between" hover={false}>
              <div>
                <div className="flex items-center justify-between mb-4">
                  <span className="phase-pill text-xs font-medium">Stage 2 · Companion System</span>
                  <span className="text-xs font-mono text-[var(--accent-primary)]">ECG Companion</span>
                </div>

                {/* Fully visible, uncropped image container */}
                <div className="rounded-xl overflow-hidden border mb-6 bg-stone-900/30 dark:bg-black/50 p-2 md:p-4 flex items-center justify-center min-h-[300px] md:min-h-[360px]" style={{ borderColor: "var(--border-subtle)" }}>
                  <img
                    src="/images/ecg-companion.png"
                    alt="Novara ECG Companion Dual Wearable System Diagram"
                    className="w-full h-auto max-h-[420px] object-contain rounded-lg shadow-lg"
                  />
                </div>

                <h3 className="text-xl mb-3">Novara ECG Companion</h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-6">
                  High-fidelity single-lead ECG monitoring designed to attach seamlessly to your bra strap or wear on your second wrist.
                </p>

                {/* Dual Mode Switcher Pill */}
                <div className="flex gap-2 p-1 rounded-xl mb-6 border" style={{ background: "var(--glass-bg)", borderColor: "var(--border-subtle)" }}>
                  <button
                    onClick={() => setActiveEcgMode("bra")}
                    className={`flex-1 py-2 px-3 rounded-lg text-xs font-medium transition-all ${activeEcgMode === "bra" ? "bg-[var(--accent-primary)] text-[var(--bg-deep)] shadow" : "text-[var(--text-secondary)]"}`}
                  >
                    1. Bra Strap Mode
                  </button>
                  <button
                    onClick={() => setActiveEcgMode("wrist")}
                    className={`flex-1 py-2 px-3 rounded-lg text-xs font-medium transition-all ${activeEcgMode === "wrist" ? "bg-[var(--accent-primary)] text-[var(--bg-deep)] shadow" : "text-[var(--text-secondary)]"}`}
                  >
                    2. Second Wrist Mode
                  </button>
                </div>

                <div className="space-y-3 border-t pt-4" style={{ borderColor: "var(--border-subtle)" }}>
                  {[
                    { title: "Single-Lead Clinical ECG", detail: "Clinical-grade ECG waveform for heart rate, HRV, & rhythm analysis" },
                    { title: activeEcgMode === "bra" ? "Optimal Chest Contact" : "Convenient Wrist Access", detail: activeEcgMode === "bra" ? "Attaches to bra strap for direct chest placement & high-quality ECG" : "Wear on opposite wrist when not using chest strap mode" },
                    { title: "Detachable & Versatile", detail: "Easily switch between modes to fit your daily workflow" },
                    { title: "Long Battery Life", detail: "Up to 5–7 days of continuous ECG tracking per charge" },
                    { title: "Combined Physiology", detail: "Hand PPG + Chest ECG = Complete physiological baseline picture" },
                  ].map((item) => (
                    <div key={item.title} className="flex items-start gap-3 text-left">
                      <div className="w-5 h-5 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5" style={{ background: "var(--nav-active-bg)", color: "var(--accent-primary)" }}>
                        <Check size={12} strokeWidth={2.5} />
                      </div>
                      <div>
                        <div className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{item.title}</div>
                        <div className="text-[11px] text-[var(--text-secondary)]">{item.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </GlassCard>

          </div>
        </section>


        {/* ═══════════════════════════════════════
           3. WHY CURRENT WEARABLES FALL SHORT
           ═══════════════════════════════════════ */}
        <section className="landing-section reveal-on-scroll">
          <div className="section-divider mb-16" />
          <div className="max-w-2xl mx-auto text-center mb-12">
            <div className="section-label mb-4">The Problem</div>
            <h2>Why Current Wearables Fall Short</h2>
            <p className="section-subtitle mx-auto mt-6">
              Traditional wrist wearables prioritize convenience over signal quality.
              Small changes in placement, motion, and skin contact significantly affect physiological measurements.
            </p>
            <p className="text-[var(--text-secondary)] leading-relaxed mt-5 max-w-xl mx-auto">
              Novara explores a different approach — rethinking where and how physiological
              signals are captured to improve consistency while remaining comfortable for everyday wear.
            </p>
          </div>

          {/* Signal comparison chart */}
          <div className="grid md:grid-cols-2 gap-6">
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center justify-between mb-2">
                <LabelCaps>Conventional wrist PPG signal</LabelCaps>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">SNR ~42%</span>
              </div>
              <div className="h-32 mt-4">
                <ResponsiveContainer>
                  <LineChart data={ppgData.map((d, i) => ({ ...d, v: d.v + Math.sin(i * 2.3) * 18 + Math.random() * 14 }))}>
                    <Line type="monotone" dataKey="v" stroke={t.wristColor} strokeWidth={1.2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="text-xs text-[var(--text-secondary)] mt-3">Noisy · high motion artifact · attenuated capillary amplitude</div>
            </GlassCard>
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center justify-between mb-2">
                <LabelCaps>Novara Finger PPG Signal</LabelCaps>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">SNR ~88%</span>
              </div>
              <div className="h-32 mt-4">
                <ResponsiveContainer>
                  <LineChart data={ppgData}>
                    <Line type="monotone" dataKey="v" stroke={t.novaraColor} strokeWidth={1.8} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="text-xs mt-3" style={{ color: "var(--accent-primary)" }}>Clean · high amplitude · direct digital arterial contact</div>
            </GlassCard>
          </div>
        </section>


        {/* ═══════════════════════════════════════
           4. INSIDE THE SIGNAL
           ═══════════════════════════════════════ */}
        <section className="landing-section reveal-on-scroll" id="technology">
          <div className="section-divider mb-16" />
          <div className="text-center mb-12">
            <div className="section-label mb-4">Signal Engineering</div>
            <h2>Inside the Signal</h2>
            <p className="section-subtitle mx-auto mt-4">
              Real physiological data, continuously captured across both optical PPG and single-lead ECG modalities.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-6 mb-6">
            {/* PPG Optical Pulse */}
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center gap-2 mb-1">
                <Activity size={14} strokeWidth={1.5} style={{ color: "var(--accent-primary)" }} />
                <LabelCaps>PPG Optical Pulse</LabelCaps>
              </div>
              <div className="stat-num mt-2" style={{ fontSize: 24 }}>Palmar Digital</div>
              <div className="h-24 mt-4">
                <ResponsiveContainer>
                  <AreaChart data={ppgData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id={`ppg-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={t.chartFillTop} stopOpacity={1} />
                        <stop offset="100%" stopColor={t.chartFillBot} stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <Area type="monotone" dataKey="v" stroke={t.chartStroke1} strokeWidth={1.5} fill={`url(#ppg-fill-${mode})`} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>

            {/* Single-Lead ECG Rhythm */}
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center gap-2 mb-1">
                <Heart size={14} strokeWidth={1.5} style={{ color: "var(--accent-primary)" }} />
                <LabelCaps>ECG Companion Rhythm</LabelCaps>
              </div>
              <div className="stat-num mt-2" style={{ fontSize: 24 }}>Single-Lead ECG</div>
              <div className="h-24 mt-4">
                <ResponsiveContainer>
                  <LineChart data={ecgData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                    <Line type="monotone" dataKey="ecg" stroke={t.chartStroke3} strokeWidth={1.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>

            {/* HRV RMSSD */}
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center gap-2 mb-1">
                <Zap size={14} strokeWidth={1.5} style={{ color: "var(--accent-primary)" }} />
                <LabelCaps>Heart Rate Variability</LabelCaps>
              </div>
              <div className="stat-num mt-2" style={{ fontSize: 24 }}>58<span className="text-sm text-[var(--text-secondary)] ml-2 font-sans">ms RMSSD</span></div>
              <div className="h-24 mt-4">
                <ResponsiveContainer>
                  <LineChart data={hrvSpark}>
                    <Line type="monotone" dataKey="v" stroke={t.chartStroke2} strokeWidth={1.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          </div>

          <div className="grid md:grid-cols-3 gap-6 mb-6">
            {/* Signal-to-Noise Comparison */}
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center gap-2 mb-1">
                <Radio size={14} strokeWidth={1.5} style={{ color: "var(--accent-primary)" }} />
                <LabelCaps>Signal-to-Noise Ratio</LabelCaps>
              </div>
              <div className="flex flex-col gap-3 mt-5">
                {signalQuality.map((sq) => (
                  <div key={sq.t} className="flex items-center gap-3">
                    <span className="text-xs text-[var(--text-secondary)] w-28 truncate">{sq.t}</span>
                    <div className="flex-1 h-2 rounded-full" style={{ background: "var(--border-subtle)" }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${sq.snr}%`,
                          background: sq.t.includes("Novara")
                            ? `linear-gradient(90deg, ${t.chartStroke1}, ${t.chartStroke3})`
                            : "var(--text-secondary)",
                          opacity: sq.t.includes("Novara") ? 1 : 0.4,
                        }}
                      />
                    </div>
                    <span className="text-xs font-mono font-medium" style={{
                      color: sq.t.includes("Novara") ? "var(--accent-primary)" : "var(--text-secondary)",
                    }}>{sq.snr}%</span>
                  </div>
                ))}
              </div>
            </GlassCard>

            {/* Motion vs Signal Filter */}
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center gap-2 mb-1">
                <Activity size={14} strokeWidth={1.5} style={{ color: "var(--accent-primary)" }} />
                <LabelCaps>3-Axis Motion Filter</LabelCaps>
              </div>
              <div className="h-32 mt-4">
                <ResponsiveContainer>
                  <LineChart data={motionData} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                    <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} />
                    <Line type="monotone" dataKey="signal" stroke={t.chartStroke1} strokeWidth={1.5} dot={false} />
                    <Line type="monotone" dataKey="motion" stroke={t.wristColor} strokeWidth={1} dot={false} strokeDasharray="3 3" opacity={0.6} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="text-xs text-[var(--text-secondary)] mt-1">
                <span style={{ color: t.novaraColor }}>—</span> filtered PPG signal &nbsp;
                <span style={{ color: t.wristColor }}>- -</span> motion vector
              </div>
            </GlassCard>

            {/* Temperature Baseline */}
            <GlassCard className="p-5 md:p-6" hover={false}>
              <div className="flex items-center gap-2 mb-1">
                <Thermometer size={14} strokeWidth={1.5} style={{ color: "var(--accent-primary)" }} />
                <LabelCaps>Precision Skin Temperature</LabelCaps>
              </div>
              <div className="stat-num mt-2" style={{ fontSize: 24 }}>36.4<span className="text-sm text-[var(--text-secondary)] ml-2 font-sans">°C avg</span></div>
              <div className="h-24 mt-4">
                <ResponsiveContainer>
                  <AreaChart data={tempData} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id={`temp-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={t.chartFillTop} stopOpacity={0.6} />
                        <stop offset="100%" stopColor={t.chartFillBot} stopOpacity={1} />
                      </linearGradient>
                    </defs>
                    <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[36, 37]} />
                    <Area type="monotone" dataKey="temp" stroke={t.chartStroke3} strokeWidth={1.5} fill={`url(#temp-fill-${mode})`} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </GlassCard>
          </div>

          {/* Interactive Live Bio-Feedback Simulator */}
          <LivePulseSimulator />
        </section>


        {/* ═══════════════════════════════════════
           5. HARDWARE DESIGN & CUSTOMIZER
           ═══════════════════════════════════════ */}
        <section className="landing-section reveal-on-scroll" id="design">
          <div className="section-divider mb-16" />
          <div className="text-center mb-12">
            <div className="section-label mb-4">Industrial Design</div>
            <h2>Designed to disappear. Engineered to sense.</h2>
            <p className="section-subtitle mx-auto mt-6">
              An ultra-soft 3D-knit textile structure follows the ulnar axis of the hand, placing the PPG sensor capsule seamlessly over the index finger.
            </p>
          </div>

          {/* Hardware Architecture Showcase */}
          <GlassCard className="p-6 md:p-10 mb-8" hover={false}>
            <div className="grid md:grid-cols-2 gap-8 items-center">
              <div>
                <span className="phase-pill text-xs font-medium mb-3">Anatomical Architecture</span>
                <h3 className="text-2xl mb-4">Precision Hand Contours & Ulnar Flow</h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-6">
                  Engineered to follow the natural biomechanics of the hand. The ultra-soft 3D-knit textile aligns along the ulnar stability zone, maintaining constant optical coupling over the index digital arteries without restrictive pressure.
                </p>

                <div className="space-y-4">
                  {[
                    { label: "Index Optical Capsule", desc: "Ultra-low profile sensor with Red (660nm) & IR (940nm) LEDs for blood volume pulse tracking." },
                    { label: "Ulnar Flow Structure", desc: "Feather-light knitted textile matrix designed for extended 24/7 all-day and sleep comfort." },
                    { label: "Wrist Main Module Pod", desc: "Houses magnetic charging terminals, low-power BLE antenna, and status pulse indicator." },
                  ].map((spec) => (
                    <div key={spec.label} className="border-l-2 pl-4 py-1" style={{ borderColor: "var(--accent-primary)" }}>
                      <div className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{spec.label}</div>
                      <div className="text-xs text-[var(--text-secondary)] mt-0.5">{spec.desc}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Uncropped Device Closeup Diagram */}
              <div className="rounded-2xl border bg-black/30 p-3 md:p-4 flex items-center justify-center" style={{ borderColor: "var(--border-subtle)" }}>
                <img
                  src="/images/device-closeup.png"
                  alt="Novara Hand Wearable Anatomical Design Specifications"
                  className="w-full h-auto max-h-[460px] object-contain rounded-xl shadow-xl"
                />
              </div>
            </div>
          </GlassCard>

          {/* Design Specifications Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-8">
            {[
              { label: "Weight", value: "<15g", sub: "Feather-light second skin" },
              { label: "PPG Wavelengths", value: "660 & 940nm", sub: "Red & Infra-Red dual LEDs" },
              { label: "Battery Life", value: "3–5 Days", sub: "Continuous sensing pod" },
              { label: "Materials", value: "3D Knit", sub: "Medical-grade hypoallergenic" },
            ].map((m) => (
              <GlassCard key={m.label} className="p-4 md:p-5 text-center" hover={false}>
                <LabelCaps>{m.label}</LabelCaps>
                <div className="font-display text-xl mt-2" style={{ color: "var(--text-primary)" }}>{m.value}</div>
                <div className="text-xs text-[var(--text-secondary)] mt-1">{m.sub}</div>
              </GlassCard>
            ))}
          </div>
        </section>


        {/* ═══════════════════════════════════════
           6. CORE TECHNOLOGIES & FEATURES
           ═══════════════════════════════════════ */}
        <section className="landing-section reveal-on-scroll" id="features">
          <div className="section-divider mb-16" />
          <div className="text-center mb-12">
            <div className="section-label mb-4">Platform Architecture</div>
            <h2>Core Platform Technologies</h2>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[
              { icon: Radio, title: "PPG Optical Matrix", desc: "Dual Red (660nm) & IR (940nm) LEDs focused at the index finger digital arteries for high-amplitude optical pulse acquisition." },
              { icon: Heart, title: "ECG Companion Strap", desc: "Detachable single-lead ECG module with dual Bra Strap & Wrist modes for clinical-grade HRV & rhythm analysis." },
              { icon: Thermometer, title: "Precision Skin Temp", desc: "Thermal sensing matrix tracking subtle circadian, metabolic, and vascular baseline shifts continuously." },
              { icon: Feather, title: "Anatomical Ulnar Fit", desc: "3D-knit textile construction that aligns along the ulnar hand axis, eliminating rigid pressure points." },
              { icon: Battery, title: "Low Power Pod Architecture", desc: "Custom power-managed sensor capsule offering multi-day battery life with magnetic charging." },
              { icon: FlaskConical, title: "Research-Driven Baseline", desc: "Built to map individualized physiological baselines over time rather than arbitrary 10,000 step counters." },
            ].map((tech) => (
              <GlassCard key={tech.title} className="p-5 md:p-6">
                <tech.icon size={20} strokeWidth={1.5} style={{ color: "var(--accent-primary)" }} />
                <h3 className="mt-4 mb-2 text-base">{tech.title}</h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{tech.desc}</p>
              </GlassCard>
            ))}
          </div>
        </section>


        {/* ═══════════════════════════════════════
           7. ROADMAP & VISION
           ═══════════════════════════════════════ */}
        <section className="landing-section reveal-on-scroll" id="roadmap">
          <div className="section-divider mb-16" />
          <div className="text-center mb-12">
            <div className="section-label mb-4">Vision</div>
            <h2>Platform Roadmap</h2>
          </div>

          <div className="max-w-xl mx-auto">
            {[
              { title: "Stage 1 · Hand Sensing Platform", desc: "Anatomical 3D knit wearable featuring index finger PPG optical pulse, skin temperature, 3-axis accelerometer & baseline learning.", active: true },
              { title: "Stage 2 · ECG Companion System", desc: "Dual-mode single-lead ECG strap (Bra strap & Wrist mode) for integrated clinical HRV, rhythm analysis, and maternal monitoring.", active: true },
              { title: "Stage 3 · Clinical Validation & Research", desc: "Partnering with physiological researchers to benchmark baseline metrics against clinical reference standards.", active: false },
              { title: "Stage 4 · Predictive Baseline Intelligence", desc: "Advanced long-term baseline modeling to provide individualized early physiological trend insights.", active: false },
            ].map((step) => (
              <div key={step.title} className="timeline-item">
                <div className={`timeline-dot ${step.active ? "active" : ""}`} />
                <h3 className="mb-2 text-base font-medium" style={{ color: "var(--text-primary)" }}>{step.title}</h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{step.desc}</p>
              </div>
            ))}
          </div>
        </section>


        {/* ═══════════════════════════════════════
           8. FOOTER
           ═══════════════════════════════════════ */}
        <footer className="landing-section" style={{ paddingBottom: 40 }}>
          <div className="section-divider mb-12" />
          <div className="flex flex-col md:flex-row justify-between items-start gap-8">
            <div>
              <div className="flex items-center gap-2.5 mb-2">
                <div className="w-7 h-7 rounded-full border flex items-center justify-center" style={{ borderColor: "var(--accent-primary)", color: "var(--accent-primary)" }}>
                  <NovaraLogo className="w-4 h-4" />
                </div>
                <span className="font-display text-xl tracking-wide" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  novara
                </span>
              </div>
              <p className="text-sm text-[var(--text-secondary)] max-w-xs leading-relaxed">
                Next-generation physiological sensing platform.
                Continuous monitoring for personalized understanding.
              </p>
            </div>
            <div className="flex flex-wrap gap-x-8 gap-y-3 text-sm">
              {[
                { label: "Technology", href: "#technology" },
                { label: "Design", href: "#design" },
                { label: "Features", href: "#features" },
                { label: "Roadmap", href: "#roadmap" },
                { label: "Contact", href: "#" },
                { label: "Privacy", href: "#" },
                { label: "Terms", href: "#" },
              ].map((link) => (
                <a
                  key={link.label}
                  href={link.href}
                  className="transition-colors"
                  style={{ color: "var(--text-secondary)" }}
                  onClick={(e) => {
                    if (link.href.startsWith("#") && link.href !== "#") {
                      e.preventDefault();
                      document.querySelector(link.href)?.scrollIntoView({ behavior: "smooth" });
                    }
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text-primary)")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-secondary)")}
                >
                  {link.label}
                </a>
              ))}
            </div>
          </div>
          <div className="mt-10 pt-6 border-t text-xs text-[var(--text-secondary)] flex flex-col sm:flex-row justify-between gap-4" style={{ borderColor: "var(--border-subtle)" }}>
            <div>© {new Date().getFullYear()} Novara Inc. All rights reserved.</div>
            <div>Continuous Sensing Platform</div>
          </div>
        </footer>

      </div>
    </Layout>
  );
}
