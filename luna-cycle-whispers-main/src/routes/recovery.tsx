import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { ScoreRing } from "@/components/ScoreRing";
import {
  AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip,
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  LineChart, Line,
} from "recharts";
import { Activity, Heart, Moon, Zap, Thermometer, TrendingUp } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";

export const Route = createFileRoute("/recovery")({
  head: () => ({
    meta: [
      { title: "Recovery & Readiness — Novara" },
      { name: "description", content: "Understand your body's readiness. Track recovery trends, strain balance, and daily readiness scores." },
    ],
  }),
  component: RecoveryPage,
});

/* ═══════════════════════════════════════════
   SYNTHETIC RECOVERY DATA
   ═══════════════════════════════════════════ */

const readinessHistory = [
  { d: "Mon", score: 72 }, { d: "Tue", score: 68 }, { d: "Wed", score: 75 },
  { d: "Thu", score: 82 }, { d: "Fri", score: 78 }, { d: "Sat", score: 85 }, { d: "Sun", score: 82 },
];

const strainVsRecovery = Array.from({ length: 14 }, (_, i) => ({
  d: i + 1,
  strain: 40 + Math.sin(i * 0.7) * 20 + Math.random() * 10,
  recovery: 60 + Math.cos(i * 0.5) * 15 + Math.random() * 10,
}));

const radarData = [
  { k: "Sleep Quality", v: 84 },
  { k: "HRV Balance", v: 72 },
  { k: "Activity Load", v: 65 },
  { k: "Resting HR", v: 88 },
  { k: "Skin Temp", v: 91 },
  { k: "Stress Level", v: 78 },
];

const recoveryTrend30 = Array.from({ length: 30 }, (_, i) => ({
  d: i + 1,
  score: 65 + Math.sin(i / 4) * 12 + Math.random() * 8,
}));

function RecoveryPage() {
  const { mode } = useTheme();

  const t = mode === "day" ? {
    stroke1: "#C0846D", stroke2: "#8A7E72", stroke3: "#D4A98A",
    fillTop: "rgba(192, 132, 109, 0.22)", fillBot: "rgba(192, 132, 109, 0.0)",
    radarStroke: "#C0846D", radarFill: "rgba(192,132,109,0.25)",
    gridStroke: "rgba(140,120,100,0.15)",
  } : {
    stroke1: "#4FD1C5", stroke2: "#63B3ED", stroke3: "#81E6D9",
    fillTop: "rgba(79, 209, 197, 0.22)", fillBot: "rgba(79, 209, 197, 0.0)",
    radarStroke: "#4FD1C5", radarFill: "rgba(79,209,197,0.25)",
    gridStroke: "rgba(79,209,197,0.12)",
  };

  const tooltipStyle = {
    background: mode === "day" ? "rgba(250,247,244,0.95)" : "rgba(8,18,35,0.95)",
    border: `1px solid ${mode === "day" ? "rgba(192,132,109,0.3)" : "rgba(79,209,197,0.3)"}`,
    borderRadius: 12,
    color: "var(--text-primary)",
  };

  return (
    <Layout>
      <div className="fade-in-up">
        <LabelCaps>Recovery</LabelCaps>
        <h1 className="mt-2 mb-2">Your readiness today</h1>
        <p className="text-[var(--text-secondary)] mb-8">
          Your body is well recovered. Good day for higher-intensity activity.
        </p>

        {/* ── Readiness Score + Contributors ── */}
        <div className="grid md:grid-cols-[auto_1fr] gap-8 mb-6 items-center">
          <div className="flex justify-center">
            <ScoreRing score={82} label="Readiness" sublabel="Good" size={200} />
          </div>
          <GlassCard hover={false}>
            <h3 className="mb-5">What's driving your score</h3>
            <div className="space-y-4">
              {[
                { icon: <Moon size={14} />, label: "Sleep", value: "84/100", desc: "7h 42m, good deep sleep", pct: 84 },
                { icon: <Zap size={14} />, label: "HRV Balance", value: "72/100", desc: "62ms — slightly below baseline", pct: 72 },
                { icon: <Heart size={14} />, label: "Resting HR", value: "88/100", desc: "58 bpm — lower than avg", pct: 88 },
                { icon: <Thermometer size={14} />, label: "Temperature", value: "91/100", desc: "+0.2°C — within range", pct: 91 },
                { icon: <Activity size={14} />, label: "Prior Activity", value: "65/100", desc: "Moderate strain yesterday", pct: 65 },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-3">
                  <span style={{ color: "var(--accent-primary)" }}>{item.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-center">
                      <span className="text-sm" style={{ color: "var(--text-primary)" }}>{item.label}</span>
                      <span className="text-xs" style={{ color: "var(--accent-primary)" }}>{item.value}</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full mt-1" style={{ background: "var(--border-subtle)" }}>
                      <div className="h-full rounded-full" style={{
                        width: `${item.pct}%`,
                        background: `linear-gradient(90deg, ${t.stroke1}, ${t.stroke3})`,
                      }} />
                    </div>
                    <div className="text-xs text-[var(--text-secondary)] mt-0.5">{item.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
        </div>

        {/* ── Strain vs Recovery ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Strain vs Recovery — 14 days</LabelCaps>
          <p className="text-sm text-[var(--text-secondary)] mt-1 mb-4">
            Keeping strain below recovery helps avoid overtraining
          </p>
          <div className="h-56">
            <ResponsiveContainer>
              <AreaChart data={strainVsRecovery} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id={`recovery-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={t.fillTop} stopOpacity={0.8} />
                    <stop offset="100%" stopColor={t.fillBot} stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="d" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[0, 100]} />
                <Tooltip contentStyle={tooltipStyle} />
                <Area type="monotone" dataKey="recovery" stroke={t.stroke1} strokeWidth={2} fill={`url(#recovery-fill-${mode})`} dot={false} />
                <Area type="monotone" dataKey="strain" stroke={t.stroke2} strokeWidth={1.5} fill="transparent" strokeDasharray="4 4" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-4 mt-2 text-xs text-[var(--text-secondary)]">
            <span><span style={{ color: t.stroke1 }}>—</span> Recovery</span>
            <span><span style={{ color: t.stroke2 }}>- -</span> Strain</span>
          </div>
        </GlassCard>

        {/* ── Radar Profile ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Your readiness profile</LabelCaps>
          <h3 className="mt-1 mb-2">Today's balance across dimensions</h3>
          <div className="h-72">
            <ResponsiveContainer>
              <RadarChart data={radarData}>
                <PolarGrid stroke={t.gridStroke} />
                <PolarAngleAxis dataKey="k" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
                <Radar dataKey="v" stroke={t.radarStroke} fill={t.radarFill} strokeWidth={2} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        {/* ── Weekly Readiness ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Weekly readiness</LabelCaps>
          <h3 className="mt-1 mb-4">How this week is going</h3>
          <div className="grid grid-cols-7 gap-2">
            {readinessHistory.map((day) => {
              const quality = day.score >= 80 ? "high" : day.score >= 65 ? "mid" : "low";
              return (
                <div key={day.d} className="flex flex-col items-center gap-2">
                  <div className="text-xs text-[var(--text-secondary)]">{day.d}</div>
                  <div
                    className="w-full rounded-lg flex items-end justify-center"
                    style={{
                      height: 80,
                      background: "var(--glass-bg)",
                      border: "1px solid var(--border-subtle)",
                    }}
                  >
                    <div
                      className="w-full rounded-lg"
                      style={{
                        height: `${day.score}%`,
                        background: quality === "high"
                          ? `linear-gradient(180deg, ${t.stroke1}, ${t.stroke3})`
                          : quality === "mid"
                            ? `linear-gradient(180deg, ${t.stroke2}, ${t.stroke1})`
                            : "var(--border-subtle)",
                        opacity: quality === "low" ? 0.5 : 0.8,
                        borderRadius: "0 0 7px 7px",
                      }}
                    />
                  </div>
                  <div className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>
                    {day.score}
                  </div>
                </div>
              );
            })}
          </div>
        </GlassCard>

        {/* ── Recommendations ── */}
        <GlassCard hover={false}>
          <LabelCaps>Today's recommendations</LabelCaps>
          <h3 className="mt-1 mb-4">Based on your readiness score</h3>
          <div className="grid md:grid-cols-2 gap-4">
            {[
              { icon: "🏃", title: "Activity", desc: "Good day for higher intensity. Your body is recovered and ready.", tag: "Go for it" },
              { icon: "😴", title: "Sleep target", desc: "Aim for 7.5–8 hours tonight. Bedtime around 11:00 PM.", tag: "On track" },
              { icon: "🧘", title: "Recovery", desc: "Consider a stretch session or cold exposure to maintain momentum.", tag: "Optional" },
              { icon: "💧", title: "Hydration", desc: "Stay ahead of hydration — aim for 2.5L today based on your activity.", tag: "Important" },
            ].map((rec) => (
              <div key={rec.title} className="p-5 rounded-2xl" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
                <div className="flex items-start gap-4">
                  <div className="text-2xl">{rec.icon}</div>
                  <div className="flex-1">
                    <div className="flex justify-between items-center">
                      <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{rec.title}</span>
                      <span className="text-xs px-2 py-1 rounded-full"
                        style={{
                          background: mode === "day" ? "rgba(192,132,109,0.12)" : "rgba(79,209,197,0.12)",
                          color: "var(--accent-primary)",
                        }}>{rec.tag}</span>
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] mt-1">{rec.desc}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </Layout>
  );
}
