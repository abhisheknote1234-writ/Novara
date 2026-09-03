import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { MetricCard } from "@/components/MetricCard";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, ResponsiveContainer, Tooltip,
} from "recharts";
import { Flame, Footprints, Timer, Heart, TrendingUp, Zap, Brain } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";

export const Route = createFileRoute("/activity")({
  head: () => ({
    meta: [
      { title: "Activity & Stress — Novara" },
      { name: "description", content: "Track your daily activity, stress levels, and strain score. Understand how your body responds to physical load." },
    ],
  }),
  component: ActivityPage,
});

/* ═══════════════════════════════════════════
   SYNTHETIC ACTIVITY DATA
   ═══════════════════════════════════════════ */

const stressTimeline = Array.from({ length: 24 }, (_, i) => {
  const base = i < 6 ? 15 : i < 8 ? 25 : i < 10 ? 45 : i < 12 ? 60 : i < 14 ? 40 : i < 17 ? 55 : i < 20 ? 35 : 20;
  return { h: `${i}:00`, stress: base + Math.floor(Math.random() * 12 - 6) };
});

const weeklySteps = [
  { d: "Mon", steps: 8420 }, { d: "Tue", steps: 6130 }, { d: "Wed", steps: 10250 },
  { d: "Thu", steps: 7800 }, { d: "Fri", steps: 9100 }, { d: "Sat", steps: 12400 }, { d: "Sun", steps: 5600 },
];

const hourlyActivity = Array.from({ length: 24 }, (_, i) => {
  const base = i < 6 ? 0 : i < 8 ? 20 : i < 12 ? 60 : i < 14 ? 30 : i < 18 ? 50 : i < 21 ? 40 : 10;
  return { h: `${i}h`, active: base + Math.floor(Math.random() * 15) };
});

const stressVsActivity = Array.from({ length: 14 }, (_, i) => ({
  d: i + 1,
  stress: 30 + Math.sin(i * 0.6) * 20 + Math.random() * 10,
  activity: 40 + Math.cos(i * 0.4) * 25 + Math.random() * 10,
}));

const sparkGen = () => Array.from({ length: 14 }, (_, i) => ({ v: 50 + Math.sin(i) * 10 + Math.random() * 5 }));

function ActivityPage() {
  const { mode } = useTheme();

  const t = mode === "day" ? {
    stroke1: "#C0846D", stroke2: "#8A7E72", stroke3: "#D4A98A",
    fillTop: "rgba(192, 132, 109, 0.22)", fillBot: "rgba(192, 132, 109, 0.0)",
    stressLow: "#7A9A6D", stressMed: "#C0846D", stressHigh: "#C06D6D",
  } : {
    stroke1: "#4FD1C5", stroke2: "#63B3ED", stroke3: "#81E6D9",
    fillTop: "rgba(79, 209, 197, 0.22)", fillBot: "rgba(79, 209, 197, 0.0)",
    stressLow: "#68D391", stressMed: "#4FD1C5", stressHigh: "#FC8181",
  };

  const tooltipStyle = {
    background: mode === "day" ? "rgba(250,247,244,0.95)" : "rgba(8,18,35,0.95)",
    border: `1px solid ${mode === "day" ? "rgba(192,132,109,0.3)" : "rgba(79,209,197,0.3)"}`,
    borderRadius: 12,
    color: "var(--text-primary)",
  };

  const currentStress = 38;
  const stressLabel = currentStress < 30 ? "Low" : currentStress < 60 ? "Moderate" : "High";
  const stressColor = currentStress < 30 ? t.stressLow : currentStress < 60 ? t.stressMed : t.stressHigh;

  return (
    <Layout>
      <div className="fade-in-up">
        <LabelCaps>Activity & Stress</LabelCaps>
        <h1 className="mt-2 mb-2">Stay balanced</h1>
        <p className="text-[var(--text-secondary)] mb-8">
          8,420 steps today · Stress is moderate · Keep moving
        </p>

        {/* ── Stress Score ── */}
        <div className="grid md:grid-cols-[260px_1fr] gap-6 mb-6">
          <GlassCard hover={false} className="flex flex-col items-center justify-center">
            <LabelCaps>Current stress</LabelCaps>
            <div className="relative w-36 h-36 mt-4">
              <svg viewBox="0 0 100 100" className="w-36 h-36">
                <circle cx="50" cy="50" r="42" fill="none" stroke="var(--border-subtle)" strokeWidth="6" />
                <circle cx="50" cy="50" r="42" fill="none" stroke={stressColor} strokeWidth="6"
                  strokeDasharray={`${(currentStress / 100) * 264} 264`} strokeLinecap="round"
                  transform="rotate(-90 50 50)"
                  style={{ filter: `drop-shadow(0 0 6px ${stressColor})` }} />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <div className="font-display text-4xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  {currentStress}
                </div>
                <div className="text-xs" style={{ color: stressColor }}>{stressLabel}</div>
              </div>
            </div>
            <p className="text-xs text-[var(--text-secondary)] mt-4 text-center">
              Based on HRV, heart rate, and skin conductance
            </p>
          </GlassCard>

          <GlassCard hover={false}>
            <LabelCaps>Stress timeline — today</LabelCaps>
            <div className="h-48 mt-4">
              <ResponsiveContainer>
                <AreaChart data={stressTimeline} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`stress-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={t.fillTop} stopOpacity={0.8} />
                      <stop offset="100%" stopColor={t.fillBot} stopOpacity={1} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="h" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 10 }} axisLine={false} tickLine={false} interval={3} />
                  <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[0, 100]} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Area type="monotone" dataKey="stress" stroke={t.stroke1} strokeWidth={1.5} fill={`url(#stress-fill-${mode})`} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </GlassCard>
        </div>

        {/* ── Activity Metrics ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <MetricCard icon={<Footprints size={14} />} label="Steps" value="8,420" trend="up" trendLabel="+12% vs avg" sparkData={sparkGen()} />
          <MetricCard icon={<Flame size={14} />} label="Calories" value="2,140" unit="kcal" trend="up" trendLabel="Active day" sparkData={sparkGen()} />
          <MetricCard icon={<Timer size={14} />} label="Active time" value="48" unit="min" trend="flat" trendLabel="On pace" sparkData={sparkGen()} />
          <MetricCard icon={<TrendingUp size={14} />} label="Strain score" value="12.4" trend="up" trendLabel="Moderate load" sparkData={sparkGen()} />
        </div>

        {/* ── Weekly Steps ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Steps — this week</LabelCaps>
          <div className="flex items-baseline gap-2 mt-1 mb-4">
            <span className="font-display text-2xl" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>8,529</span>
            <span className="text-sm text-[var(--text-secondary)]">daily average</span>
          </div>
          <div className="h-40">
            <ResponsiveContainer>
              <BarChart data={weeklySteps} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="d" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="steps" fill={t.stroke1} radius={[6, 6, 0, 0]} opacity={0.8} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── Stress vs Activity Correlation ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Stress vs Activity — 14 days</LabelCaps>
          <p className="text-sm text-[var(--text-secondary)] mt-1 mb-4">
            Understanding how activity impacts your stress response
          </p>
          <div className="h-48">
            <ResponsiveContainer>
              <LineChart data={stressVsActivity} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="d" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[0, 100]} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="stress" stroke={t.stroke2} strokeWidth={1.5} dot={false} strokeDasharray="4 4" />
                <Line type="monotone" dataKey="activity" stroke={t.stroke1} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-4 mt-2 text-xs text-[var(--text-secondary)]">
            <span><span style={{ color: t.stroke1 }}>—</span> Activity</span>
            <span><span style={{ color: t.stroke2 }}>- -</span> Stress</span>
          </div>
        </GlassCard>

        {/* ── Goals ── */}
        <GlassCard hover={false}>
          <LabelCaps>Daily goals</LabelCaps>
          <h3 className="mt-1 mb-4">Keep up the momentum</h3>
          <div className="space-y-4">
            {[
              { label: "Steps", current: 8420, goal: 10000, unit: "steps" },
              { label: "Active minutes", current: 48, goal: 60, unit: "min" },
              { label: "Calories burned", current: 2140, goal: 2500, unit: "kcal" },
              { label: "Stand hours", current: 9, goal: 12, unit: "hours" },
            ].map((g) => (
              <div key={g.label}>
                <div className="flex justify-between text-sm mb-1">
                  <span style={{ color: "var(--text-primary)" }}>{g.label}</span>
                  <span className="text-xs text-[var(--text-secondary)]">
                    {g.current.toLocaleString()} / {g.goal.toLocaleString()} {g.unit}
                  </span>
                </div>
                <div className="w-full h-2 rounded-full" style={{ background: "var(--border-subtle)" }}>
                  <div className="h-full rounded-full" style={{
                    width: `${Math.min((g.current / g.goal) * 100, 100)}%`,
                    background: `linear-gradient(90deg, ${t.stroke1}, ${t.stroke3})`,
                  }} />
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </Layout>
  );
}
