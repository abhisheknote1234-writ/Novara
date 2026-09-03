import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { MetricCard } from "@/components/MetricCard";
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip,
} from "recharts";
import { Heart, Activity, Thermometer, Wind, Droplets, Zap } from "lucide-react";
import { LivePulseSimulator } from "@/components/LivePulseSimulator";
import { useTheme } from "@/context/ThemeContext";
import { useState } from "react";

export const Route = createFileRoute("/heart")({
  head: () => ({
    meta: [
      { title: "Heart & Body — Novara" },
      { name: "description", content: "Monitor your heart rate, HRV, blood oxygen, skin temperature, and respiratory rate in real time." },
    ],
  }),
  component: HeartPage,
});

/* ═══════════════════════════════════════════
   SYNTHETIC BIOMETRIC DATA
   ═══════════════════════════════════════════ */

const hr24 = Array.from({ length: 24 }, (_, i) => {
  const base = i < 6 ? 56 : i < 8 ? 62 : i < 12 ? 72 : i < 14 ? 68 : i < 18 ? 75 : i < 21 ? 70 : 60;
  return { h: `${i}:00`, bpm: base + Math.floor(Math.random() * 6 - 3) };
});

const hrv30 = Array.from({ length: 30 }, (_, i) => ({
  d: i + 1,
  v: 60 + Math.sin(i / 3) * 8 + Math.random() * 4,
}));

const tempTrend = Array.from({ length: 30 }, (_, i) => ({
  d: i + 1,
  temp: +(36.3 + Math.sin(i / 7) * 0.3 + Math.random() * 0.15).toFixed(1),
}));

const respRate = Array.from({ length: 24 }, (_, i) => {
  const base = i < 6 ? 13 : i < 12 ? 15 : i < 18 ? 16 : 14;
  return { h: `${i}h`, rate: base + Math.floor(Math.random() * 2) };
});

const sparkGen = () => Array.from({ length: 14 }, (_, i) => ({ v: 50 + Math.sin(i) * 10 + Math.random() * 5 }));

function HeartPage() {
  const { mode } = useTheme();
  const [range, setRange] = useState<"7D" | "30D" | "3M" | "All">("30D");

  const t = mode === "day" ? {
    stroke1: "#C0846D", stroke2: "#8A7E72", stroke3: "#D4A98A",
    fillTop: "rgba(192, 132, 109, 0.22)", fillBot: "rgba(192, 132, 109, 0.0)",
  } : {
    stroke1: "#4FD1C5", stroke2: "#63B3ED", stroke3: "#81E6D9",
    fillTop: "rgba(79, 209, 197, 0.22)", fillBot: "rgba(79, 209, 197, 0.0)",
  };

  const tooltipStyle = {
    background: mode === "day" ? "rgba(250,247,244,0.95)" : "rgba(8,18,35,0.95)",
    border: `1px solid ${mode === "day" ? "rgba(192,132,109,0.3)" : "rgba(79,209,197,0.3)"}`,
    borderRadius: 12,
    backdropFilter: "blur(20px)",
    color: "var(--text-primary)",
  };

  return (
    <Layout>
      <div className="fade-in-up">
        <LabelCaps>Heart & Body</LabelCaps>
        <h1 className="mt-2 mb-2">How you're doing</h1>
        <p className="text-[var(--text-secondary)] mb-6">HRV is at 62 ms · Everything looks stable</p>

        {/* ── Live PPG Bio-Feedback Simulator ── */}
        <LivePulseSimulator />

        {/* ── HRV 30-Day Trend ── */}
        <GlassCard className="mb-6" hover={false}>
          <div className="flex justify-between items-center mb-4 flex-wrap gap-3">
            <h3>Heart rate variability — last 30 days</h3>
            <div className="flex gap-2 text-xs">
              {(["7D", "30D", "3M", "All"] as const).map((r) => (
                <button key={r} onClick={() => setRange(r)} className="px-3 py-1.5 rounded-full"
                  style={{
                    background: range === r ? (mode === "day" ? "rgba(192,132,109,0.15)" : "rgba(79,209,197,0.15)") : "transparent",
                    border: `1px solid ${range === r ? "var(--accent-primary)" : "var(--border-subtle)"}`,
                    color: range === r ? "var(--accent-primary)" : "var(--text-secondary)",
                  }}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer>
              <AreaChart data={hrv30}>
                <defs>
                  <linearGradient id={`hrv-grad-${mode}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={t.fillTop} stopOpacity={1} />
                    <stop offset="100%" stopColor={t.fillBot} stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="d" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="v" stroke={t.stroke1} strokeWidth={2.5} fill={`url(#hrv-grad-${mode})`} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── Metric Cards ── */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-6">
          <MetricCard icon={<Heart size={14} />} label="Resting heart rate" value="58" unit="bpm" trend="down" trendLabel="2 bpm lower than last week" sparkData={sparkGen()} />
          <MetricCard icon={<Thermometer size={14} />} label="Skin temperature" value="+0.2" unit="°C" trend="flat" trendLabel="Normal range" sparkData={sparkGen()} />
          <MetricCard icon={<Droplets size={14} />} label="Blood oxygen" value="98" unit="%" trend="up" trendLabel="Consistently high" sparkData={sparkGen()} />
          <MetricCard icon={<Zap size={14} />} label="HRV (RMSSD)" value="62" unit="ms" trend="up" trendLabel="+4ms vs 30d avg" sparkData={sparkGen()} />
          <MetricCard icon={<Wind size={14} />} label="Respiratory rate" value="14" unit="br/min" trend="flat" trendLabel="Normal" sparkData={sparkGen()} />
          <MetricCard icon={<Activity size={14} />} label="Signal quality" value="94" unit="%" trend="up" trendLabel="Excellent sensor contact" sparkData={sparkGen()} />
        </div>

        {/* ── 24h Heart Rate ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Heart rate — 24 hours</LabelCaps>
          <div className="flex items-baseline gap-2 mt-1 mb-4">
            <span className="font-display text-2xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>68</span>
            <span className="text-sm text-[var(--text-secondary)]">avg bpm</span>
          </div>
          <div className="h-40">
            <ResponsiveContainer>
              <AreaChart data={hr24} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id={`hr24-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={t.fillTop} stopOpacity={0.6} />
                    <stop offset="100%" stopColor={t.fillBot} stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="h" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 10 }} axisLine={false} tickLine={false} interval={3} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[45, 85]} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="bpm" stroke={t.stroke1} strokeWidth={1.5} fill={`url(#hr24-fill-${mode})`} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── Autonomic Balance ── */}
        <GlassCard hover={false}>
          <LabelCaps>Autonomic nervous system</LabelCaps>
          <h3 className="mt-1 mb-6">Rest vs. fight-or-flight</h3>
          <div className="grid md:grid-cols-2 gap-8 items-center">
            <div className="relative h-40 rounded-2xl overflow-hidden"
              style={{
                background: mode === "day"
                  ? "linear-gradient(90deg, #C0846D 0%, #8A7E72 100%)"
                  : "linear-gradient(90deg, #4FD1C5 0%, #63B3ED 100%)"
              }}>
              <div className="absolute inset-0 flex">
                <div className="flex-1 flex flex-col items-center justify-center"
                  style={{ background: mode === "day" ? "rgba(245,240,235,0.6)" : "rgba(6,14,26,0.5)" }}>
                  <div className="text-xs text-[var(--text-secondary)]">Parasympathetic</div>
                  <div className="font-display text-3xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>52%</div>
                </div>
                <div className="w-px" style={{ background: "var(--border-subtle)" }} />
                <div className="flex-1 flex flex-col items-center justify-center"
                  style={{ background: mode === "day" ? "rgba(245,240,235,0.6)" : "rgba(6,14,26,0.5)" }}>
                  <div className="text-xs text-[var(--text-secondary)]">Sympathetic</div>
                  <div className="font-display text-3xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>48%</div>
                </div>
              </div>
            </div>
            <div>
              <p className="font-display text-xl" style={{ fontFamily: "var(--font-display)", color: "var(--accent-primary)" }}>
                You're well balanced today.
              </p>
              <p className="text-sm text-[var(--text-secondary)] mt-2">
                Your nervous system is leaning slightly toward rest mode, which supports recovery. No action needed — your body is doing great.
              </p>
            </div>
          </div>
        </GlassCard>
      </div>
    </Layout>
  );
}
