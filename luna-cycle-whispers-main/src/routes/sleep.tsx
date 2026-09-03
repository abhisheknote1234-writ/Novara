import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { ScoreRing } from "@/components/ScoreRing";
import { MetricCard } from "@/components/MetricCard";
import {
  AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip,
  BarChart, Bar, LineChart, Line,
} from "recharts";
import { Moon, Clock, Zap, Heart, TrendingUp } from "lucide-react";
import { CircadianClock } from "@/components/CircadianClock";
import { useTheme } from "@/context/ThemeContext";
import { useState } from "react";

export const Route = createFileRoute("/sleep")({
  head: () => ({
    meta: [
      { title: "Sleep — Novara" },
      { name: "description", content: "Track your sleep quality, stages, and trends. Understand your body's recovery patterns." },
    ],
  }),
  component: SleepPage,
});

/* ═══════════════════════════════════════════
   SYNTHETIC SLEEP DATA
   ═══════════════════════════════════════════ */

// Sleep stages — last night (8 hours, 5-min intervals = 96 data points)
const sleepStages = Array.from({ length: 96 }, (_, i) => {
  const hour = i / 12; // 0-8 hours
  let stage: number;
  // Simulate realistic sleep architecture
  if (hour < 0.3) stage = 1; // Awake → Light
  else if (hour < 0.8) stage = 2; // Light
  else if (hour < 1.5) stage = 3; // Deep
  else if (hour < 2.0) stage = 2; // Light
  else if (hour < 2.5) stage = 4; // REM
  else if (hour < 3.0) stage = 2; // Light
  else if (hour < 3.8) stage = 3; // Deep
  else if (hour < 4.3) stage = 2; // Light
  else if (hour < 5.0) stage = 4; // REM
  else if (hour < 5.5) stage = 2; // Light
  else if (hour < 6.0) stage = 4; // REM (longer)
  else if (hour < 6.8) stage = 2; // Light
  else if (hour < 7.5) stage = 4; // REM (longest)
  else stage = 1; // Waking
  // Add some noise
  if (Math.random() < 0.08) stage = Math.max(1, stage - 1);
  return { t: `${Math.floor(hour)}:${String(Math.floor((hour % 1) * 60)).padStart(2, "0")}`, stage };
});

// HR during sleep
const sleepHR = Array.from({ length: 48 }, (_, i) => {
  const hour = i / 6;
  const base = hour < 1 ? 62 : hour < 3 ? 54 : hour < 5 ? 52 : hour < 7 ? 56 : 60;
  return { t: `${Math.floor(hour)}h`, bpm: base + Math.floor(Math.random() * 6 - 3) };
});

// Weekly sleep scores
const weekScores = [
  { d: "Mon", score: 82 }, { d: "Tue", score: 78 }, { d: "Wed", score: 85 },
  { d: "Thu", score: 71 }, { d: "Fri", score: 88 }, { d: "Sat", score: 91 }, { d: "Sun", score: 84 },
];

// Sleep duration trend (30 days)
const durationTrend = Array.from({ length: 30 }, (_, i) => ({
  d: i + 1,
  hours: +(6.5 + Math.random() * 2.5).toFixed(1),
}));

// Stage labels for chart coloring
const stageLabels: Record<number, string> = { 1: "Awake", 2: "Light", 3: "Deep", 4: "REM" };

function SleepPage() {
  const { mode } = useTheme();
  const [range, setRange] = useState<"7D" | "30D" | "3M">("7D");

  const t = mode === "day" ? {
    stroke1: "#C0846D", stroke2: "#8A7E72", stroke3: "#D4A98A",
    fillTop: "rgba(192, 132, 109, 0.22)", fillBot: "rgba(192, 132, 109, 0.0)",
    deep: "#8A7E72", light: "#D4A98A", rem: "#C0846D", awake: "#A89585",
  } : {
    stroke1: "#4FD1C5", stroke2: "#63B3ED", stroke3: "#81E6D9",
    fillTop: "rgba(79, 209, 197, 0.22)", fillBot: "rgba(79, 209, 197, 0.0)",
    deep: "#38A89D", light: "#63B3ED", rem: "#4FD1C5", awake: "#6B97A8",
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
        <LabelCaps>Sleep</LabelCaps>
        <h1 className="mt-2 mb-2">Last night's sleep</h1>
        <p className="text-[var(--text-secondary)] mb-8">
          You slept 7h 42m · Sleep score is looking great
        </p>

        {/* ── Score + Summary ── */}
        <div className="grid md:grid-cols-[auto_1fr] gap-8 mb-6 items-center">
          <div className="flex justify-center">
            <ScoreRing score={84} label="Sleep Score" sublabel="Good" size={200} />
          </div>
          <GlassCard hover={false}>
            <h3 className="mb-4">Sleep Summary</h3>
            <div className="grid grid-cols-2 gap-4">
              {[
                { icon: <Clock size={14} />, label: "Total sleep", value: "7h 42m" },
                { icon: <Moon size={14} />, label: "Time in bed", value: "8h 15m" },
                { icon: <Zap size={14} />, label: "Sleep efficiency", value: "93%" },
                { icon: <Heart size={14} />, label: "Lowest HR", value: "48 bpm" },
              ].map((item) => (
                <div key={item.label}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <span style={{ color: "var(--accent-primary)" }}>{item.icon}</span>
                    <span className="text-xs text-[var(--text-secondary)]">{item.label}</span>
                  </div>
                  <div className="font-display text-xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                    {item.value}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex gap-3 mt-5 text-xs">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ background: t.deep }} />
                <span style={{ color: "var(--text-secondary)" }}>Deep 1h 48m</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ background: t.rem }} />
                <span style={{ color: "var(--text-secondary)" }}>REM 1h 32m</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ background: t.light }} />
                <span style={{ color: "var(--text-secondary)" }}>Light 4h 12m</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ background: t.awake }} />
                <span style={{ color: "var(--text-secondary)" }}>Awake 10m</span>
              </div>
            </div>
          </GlassCard>
        </div>

        {/* ── Sleep Stages Chart ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Sleep Stages · Last Night</LabelCaps>
          <div className="text-xs text-[var(--text-secondary)] mt-1 mb-4">11:15 PM → 7:30 AM</div>
          <div className="h-48">
            <ResponsiveContainer>
              <AreaChart data={sleepStages} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id={`sleep-stage-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={t.fillTop} stopOpacity={1} />
                    <stop offset="100%" stopColor={t.fillBot} stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="t" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 10 }} axisLine={false} tickLine={false} interval={11} />
                <YAxis
                  stroke="transparent"
                  tick={{ fill: "var(--text-secondary)", fontSize: 10 }}
                  axisLine={false} tickLine={false}
                  domain={[0.5, 4.5]}
                  ticks={[1, 2, 3, 4]}
                  tickFormatter={(v: number) => stageLabels[v] || ""}
                />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => [stageLabels[v] || v, "Stage"]} />
                <Area type="stepAfter" dataKey="stage" stroke={t.stroke1} strokeWidth={1.5} fill={`url(#sleep-stage-fill-${mode})`} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── HR During Sleep ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Heart rate during sleep</LabelCaps>
          <div className="flex items-baseline gap-2 mt-1 mb-4">
            <span className="font-display text-2xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>48</span>
            <span className="text-sm text-[var(--text-secondary)]">bpm lowest</span>
          </div>
          <div className="h-32">
            <ResponsiveContainer>
              <AreaChart data={sleepHR} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id={`sleep-hr-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={t.fillTop} stopOpacity={0.6} />
                    <stop offset="100%" stopColor={t.fillBot} stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="t" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[45, 70]} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="bpm" stroke={t.stroke1} strokeWidth={1.5} fill={`url(#sleep-hr-fill-${mode})`} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── Weekly Sleep Score ── */}
        <GlassCard className="mb-6" hover={false}>
          <div className="flex justify-between items-center mb-4 flex-wrap gap-3">
            <div>
              <LabelCaps>Sleep score trend</LabelCaps>
              <h3 className="mt-1">This week</h3>
            </div>
            <div className="flex gap-2 text-xs">
              {(["7D", "30D", "3M"] as const).map((r) => (
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
          <div className="h-40">
            <ResponsiveContainer>
              <BarChart data={weekScores} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="d" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[60, 100]} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="score" fill={t.stroke1} radius={[6, 6, 0, 0]} opacity={0.8} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── Metric Cards ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {[
            { icon: <Moon size={14} />, label: "Avg bedtime", value: "11:20", unit: "PM", trend: "flat" as const, trendLabel: "Consistent" },
            { icon: <Clock size={14} />, label: "Avg duration", value: "7.4", unit: "hrs", trend: "up" as const, trendLabel: "+0.3h vs last week" },
            { icon: <Zap size={14} />, label: "Avg efficiency", value: "91", unit: "%", trend: "up" as const, trendLabel: "+2% this month" },
            { icon: <TrendingUp size={14} />, label: "Best night", value: "Sat", unit: "91 pts", trend: "up" as const, trendLabel: "Your best this week" },
          ].map((m) => (
            <MetricCard key={m.label} {...m} />
          ))}
        </div>

        {/* ── Sleep Duration Trend ── */}
        <GlassCard hover={false}>
          <LabelCaps>Sleep duration — 30 days</LabelCaps>
          <p className="text-sm text-[var(--text-secondary)] mt-1 mb-4">
            Averaging 7.4 hours · Trending up this month
          </p>
          <div className="h-32">
            <ResponsiveContainer>
              <LineChart data={durationTrend} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="d" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[5, 10]} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="hours" stroke={t.stroke1} strokeWidth={1.5} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── Circadian Biological Rhythm Engine ── */}
        <CircadianClock />
      </div>
    </Layout>
  );
}
