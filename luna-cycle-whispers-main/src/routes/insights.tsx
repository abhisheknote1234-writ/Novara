import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { MetricCard } from "@/components/MetricCard";
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip,
} from "recharts";
import { TrendingUp, Moon, Heart, Zap, Activity, Thermometer, BarChart3, AlertCircle } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";

export const Route = createFileRoute("/insights")({
  head: () => ({
    meta: [
      { title: "Insights & Trends — Novara" },
      { name: "description", content: "Discover long-term patterns in your health data. Week-over-week comparisons, correlations, and personalized insights." },
    ],
  }),
  component: InsightsPage,
});

/* ═══════════════════════════════════════════
   SYNTHETIC TREND DATA
   ═══════════════════════════════════════════ */

const monthlyTrend = Array.from({ length: 90 }, (_, i) => ({
  d: i + 1,
  sleep: 70 + Math.sin(i / 10) * 10 + Math.random() * 5,
  hrv: 55 + Math.sin(i / 8) * 8 + Math.random() * 6,
  recovery: 65 + Math.sin(i / 12) * 12 + Math.random() * 5,
  stress: 40 + Math.cos(i / 7) * 15 + Math.random() * 8,
}));

const weekComparison = [
  { metric: "Sleep Score", thisWeek: 84, lastWeek: 79, change: "+5" },
  { metric: "Avg HRV", thisWeek: 62, lastWeek: 58, change: "+4ms" },
  { metric: "Resting HR", thisWeek: 58, lastWeek: 60, change: "-2bpm" },
  { metric: "Steps/day", thisWeek: 8529, lastWeek: 7830, change: "+699" },
  { metric: "Recovery Score", thisWeek: 82, lastWeek: 76, change: "+6" },
  { metric: "Stress Avg", thisWeek: 38, lastWeek: 44, change: "-6" },
];

const correlations = [
  { a: "Sleep Duration", b: "Next-day HRV", correlation: 0.82, insight: "Longer sleep strongly correlates with higher HRV next day" },
  { a: "Evening Activity", b: "Sleep Quality", correlation: -0.65, insight: "Late exercise tends to reduce sleep quality" },
  { a: "Consistent Bedtime", b: "Recovery Score", correlation: 0.78, insight: "Regular bedtime strongly boosts recovery" },
  { a: "High Stress Days", b: "Resting HR", correlation: 0.71, insight: "Elevated stress consistently raises resting heart rate" },
];

const sparkGen = () => Array.from({ length: 14 }, (_, i) => ({ v: 50 + Math.sin(i) * 10 + Math.random() * 5 }));

function InsightsPage() {
  const { mode } = useTheme();

  const t = mode === "day" ? {
    stroke1: "#C0846D", stroke2: "#8A7E72", stroke3: "#D4A98A", stroke4: "#A89585",
    fillTop: "rgba(192, 132, 109, 0.18)", fillBot: "rgba(192, 132, 109, 0.0)",
  } : {
    stroke1: "#4FD1C5", stroke2: "#63B3ED", stroke3: "#81E6D9", stroke4: "#38A89D",
    fillTop: "rgba(79, 209, 197, 0.18)", fillBot: "rgba(79, 209, 197, 0.0)",
  };

  const tooltipStyle = {
    background: mode === "day" ? "rgba(250,247,244,0.95)" : "rgba(8,18,35,0.95)",
    border: `1px solid ${mode === "day" ? "rgba(192,132,109,0.3)" : "rgba(79,209,197,0.3)"}`,
    borderRadius: 12,
    color: "var(--text-primary)",
  };

  const positiveColor = mode === "day" ? "#7A9A6D" : "#68D391";
  const negativeColor = mode === "day" ? "#C06D6D" : "#FC8181";

  return (
    <Layout>
      <div className="fade-in-up">
        <LabelCaps>Insights</LabelCaps>
        <h1 className="mt-2 mb-2">Your trends over time</h1>
        <p className="text-[var(--text-secondary)] mb-8">
          Novara learns your body over time. The longer you wear it, the more it understands.
        </p>

        {/* ── Highlight Insight ── */}
        <GlassCard className="mb-6" hover={false} style={{
          background: mode === "day"
            ? "linear-gradient(135deg, rgba(192,132,109,0.10), rgba(138,126,114,0.06))"
            : "linear-gradient(135deg, rgba(79,209,197,0.10), rgba(99,179,237,0.06))"
        }}>
          <div className="flex items-start gap-3">
            <AlertCircle size={18} style={{ color: "var(--accent-primary)", marginTop: 2 }} />
            <div>
              <LabelCaps>Notable pattern</LabelCaps>
              <h3 className="mt-1 mb-2">Your sleep is improving this month</h3>
              <p className="text-sm text-[var(--text-secondary)]">
                Average sleep score is up 8% compared to last month. Your consistent bedtime routine
                is paying off — HRV and recovery scores are following suit.
              </p>
            </div>
          </div>
        </GlassCard>

        {/* ── Multi-Metric Trend ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>90-day trends</LabelCaps>
          <h3 className="mt-1 mb-4">All key metrics at a glance</h3>
          <div className="h-64">
            <ResponsiveContainer>
              <LineChart data={monthlyTrend} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                <XAxis dataKey="d" stroke="transparent" tick={{ fill: "var(--text-secondary)", fontSize: 10 }} axisLine={false} tickLine={false} interval={14} />
                <YAxis stroke="transparent" tick={false} axisLine={false} tickLine={false} domain={[20, 100]} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="sleep" stroke={t.stroke1} strokeWidth={2} dot={false} name="Sleep" />
                <Line type="monotone" dataKey="hrv" stroke={t.stroke2} strokeWidth={1.5} dot={false} name="HRV" />
                <Line type="monotone" dataKey="recovery" stroke={t.stroke3} strokeWidth={1.5} dot={false} name="Recovery" />
                <Line type="monotone" dataKey="stress" stroke={t.stroke4} strokeWidth={1} dot={false} name="Stress" strokeDasharray="4 4" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap gap-4 mt-3 text-xs text-[var(--text-secondary)]">
            <span><span style={{ color: t.stroke1 }}>—</span> Sleep</span>
            <span><span style={{ color: t.stroke2 }}>—</span> HRV</span>
            <span><span style={{ color: t.stroke3 }}>—</span> Recovery</span>
            <span><span style={{ color: t.stroke4 }}>- -</span> Stress</span>
          </div>
        </GlassCard>

        {/* ── Week-over-Week ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Week-over-week comparison</LabelCaps>
          <h3 className="mt-1 mb-4">How this week stacks up</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: "var(--text-secondary)" }}>
                  <th className="py-3 pr-4 font-medium text-left">Metric</th>
                  <th className="py-3 pr-4 font-medium text-right">This Week</th>
                  <th className="py-3 pr-4 font-medium text-right">Last Week</th>
                  <th className="py-3 font-medium text-right">Change</th>
                </tr>
              </thead>
              <tbody>
                {weekComparison.map((row) => {
                  const isPositive = row.change.startsWith("+") || row.change.startsWith("-2bpm") || row.change.startsWith("-6");
                  return (
                    <tr key={row.metric} className="border-t" style={{ borderColor: "var(--border-subtle)" }}>
                      <td className="py-3 pr-4" style={{ color: "var(--accent-primary)" }}>{row.metric}</td>
                      <td className="py-3 pr-4 text-right font-display" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                        {row.thisWeek.toLocaleString()}
                      </td>
                      <td className="py-3 pr-4 text-right text-[var(--text-secondary)]">{row.lastWeek.toLocaleString()}</td>
                      <td className="py-3 text-right font-medium" style={{ color: isPositive ? positiveColor : negativeColor }}>
                        {row.change}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassCard>

        {/* ── Correlations ── */}
        <GlassCard className="mb-6" hover={false}>
          <LabelCaps>Discovered correlations</LabelCaps>
          <h3 className="mt-1 mb-2">Patterns Novara has found in your data</h3>
          <p className="text-sm text-[var(--text-secondary)] mb-4">These improve over time as more data is collected.</p>
          <div className="grid md:grid-cols-2 gap-4">
            {correlations.map((c) => (
              <div key={c.a + c.b} className="p-5 rounded-2xl" style={{
                background: "var(--glass-bg)",
                border: "1px solid var(--border-subtle)",
              }}>
                <div className="flex items-center gap-2 mb-2">
                  <BarChart3 size={14} style={{ color: "var(--accent-primary)" }} />
                  <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    {c.a} ↔ {c.b}
                  </span>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex-1 h-1.5 rounded-full" style={{ background: "var(--border-subtle)" }}>
                    <div className="h-full rounded-full" style={{
                      width: `${Math.abs(c.correlation) * 100}%`,
                      background: c.correlation > 0
                        ? `linear-gradient(90deg, ${t.stroke1}, ${t.stroke3})`
                        : `linear-gradient(90deg, ${negativeColor}, ${t.stroke2})`,
                    }} />
                  </div>
                  <span className="text-xs font-medium" style={{
                    color: c.correlation > 0 ? positiveColor : negativeColor,
                  }}>
                    {c.correlation > 0 ? "+" : ""}{c.correlation.toFixed(2)}
                  </span>
                </div>
                <p className="text-xs text-[var(--text-secondary)]">{c.insight}</p>
              </div>
            ))}
          </div>
        </GlassCard>

        {/* ── Health Tips ── */}
        <GlassCard hover={false}>
          <LabelCaps>Personalized tips</LabelCaps>
          <h3 className="mt-1 mb-4">Based on your recent trends</h3>
          <div className="space-y-3">
            {[
              { icon: "😴", tip: "Keep your bedtime between 10:30-11:00 PM — your best sleep scores happen in this window." },
              { icon: "🏃", tip: "Your recovery peaks when you keep high-intensity workouts to 3 days/week. Consider spacing them out." },
              { icon: "🧘", tip: "Morning HRV readings are more accurate. Try measuring right after waking before getting up." },
              { icon: "💧", tip: "On days you walk 10K+ steps, your sleep deep percentage improves by ~15%. Keep it up." },
            ].map((t, i) => (
              <div key={i} className="flex items-center gap-3 p-3 rounded-xl" style={{
                background: mode === "day" ? "rgba(192,132,109,0.05)" : "rgba(79,209,197,0.05)",
              }}>
                <span className="text-lg">{t.icon}</span>
                <span className="text-sm" style={{ color: "var(--text-primary)" }}>{t.tip}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </Layout>
  );
}
