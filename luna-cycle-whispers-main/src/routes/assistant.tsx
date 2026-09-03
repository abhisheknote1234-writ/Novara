import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { Mic, Send, Activity, Heart, Moon, Zap, Thermometer } from "lucide-react";
import { useState } from "react";
import { useTheme } from "@/context/ThemeContext";

export const Route = createFileRoute("/assistant")({
  head: () => ({
    meta: [
      { title: "Novara AI — Your Health Companion" },
      { name: "description", content: "Ask Novara AI anything about your health data. Private, on-device, personalized." },
    ],
  }),
  component: AssistantPage,
});

const initial = [
  {
    role: "assistant",
    text: "Good evening! Your recovery score is strong at 82 today. Sleep was solid last night — 7h 42m with good deep sleep. Your HRV dipped slightly to 62ms, but that's within your normal range. What would you like to know more about?",
  },
];

const chips = [
  "How's my recovery?",
  "Why was my HRV low?",
  "Am I overtraining?",
  "Optimize my sleep",
];

function AssistantPage() {
  const { mode } = useTheme();
  const [msgs, setMsgs] = useState(initial);
  const [input, setInput] = useState("");

  const send = (text: string) => {
    if (!text.trim()) return;
    setMsgs((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setTimeout(() => {
      setMsgs((prev) => [
        ...prev,
        {
          role: "assistant",
          text: "Based on your data, I'd recommend keeping today's activity moderate. Your HRV has been trending slightly down over the past 3 days, which suggests your body is still recovering. Try getting to bed by 11 PM tonight for optimal recovery.",
        },
      ]);
    }, 900);
  };

  return (
    <Layout>
      <div className="fade-in-up">
        <div className="flex items-center gap-4 mb-6">
          <div className="relative w-12 h-12">
            <div className="absolute inset-0 rounded-full" style={{
              background: `radial-gradient(circle, var(--accent-primary), transparent 70%)`,
              filter: "blur(8px)",
            }} />
            <div
              className="relative w-12 h-12 rounded-full border-2 flex items-center justify-center"
              style={{ borderColor: "var(--accent-primary)", background: "var(--glass-bg)" }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-primary)" strokeWidth="1.5">
                <path d="M12 2L12 22M2 12L22 12M5 5L19 19M19 5L5 19" strokeLinecap="round" />
              </svg>
            </div>
          </div>
          <div>
            <h2 style={{ fontSize: 24 }}>Novara AI</h2>
            <div className="text-sm text-[var(--text-secondary)]">Your health companion · Private & on-device</div>
          </div>
        </div>

        <div className="grid lg:grid-cols-[1fr_260px] gap-6">
          <GlassCard hover={false} className="!p-0 flex flex-col" style={{ height: "70vh" }}>
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {msgs.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className="max-w-[80%] p-4 rounded-3xl text-sm fade-in-up"
                    style={
                      m.role === "assistant"
                        ? {
                            background: "var(--glass-bg)",
                            border: `1px solid var(--border-subtle)`,
                            color: "var(--text-primary)",
                          }
                        : {
                            background: `linear-gradient(135deg, var(--accent-primary), var(--accent-tertiary))`,
                            color: mode === "day" ? "#FAF7F4" : "#060E1A",
                          }
                    }
                  >
                    {m.text}
                  </div>
                </div>
              ))}
            </div>
            <div className="p-4 border-t" style={{ borderColor: "var(--border-subtle)" }}>
              <div className="flex flex-wrap gap-2 mb-3">
                {chips.map((c) => (
                  <button
                    key={c}
                    onClick={() => send(c)}
                    className="text-xs px-3 py-1.5 rounded-full hover:scale-105 transition"
                    style={{
                      background: mode === "day" ? "rgba(192,132,109,0.10)" : "rgba(79,209,197,0.10)",
                      color: "var(--accent-primary)",
                      border: `1px solid ${mode === "day" ? "rgba(192,132,109,0.25)" : "rgba(79,209,197,0.25)"}`,
                    }}
                  >
                    {c}
                  </button>
                ))}
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send(input);
                }}
                className="flex gap-2 items-center"
              >
                <button type="button" className="p-3 rounded-2xl btn-glass">
                  <Mic size={18} />
                </button>
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask anything…"
                  className="flex-1 p-3 rounded-2xl outline-none text-sm"
                  style={{
                    background: "var(--glass-bg)",
                    border: "1px solid var(--border-subtle)",
                    color: "var(--text-primary)",
                  }}
                />
                <button type="submit" className="p-3 rounded-2xl btn-primary">
                  <Send size={18} />
                </button>
              </form>
              <p className="text-[10px] text-[var(--text-secondary)] mt-2 text-center">
                Not medical advice — insights based on your wearable data.
              </p>
            </div>
          </GlassCard>

          <GlassCard hover={false}>
            <LabelCaps>Novara knows right now</LabelCaps>
            <div className="space-y-4 mt-4">
              {[
                { icon: <Activity size={14} />, label: "Recovery", value: "82/100 · Good" },
                { icon: <Moon size={14} />, label: "Sleep", value: "7h 42m · Score 84" },
                { icon: <Zap size={14} />, label: "HRV", value: "62 ms (slightly low)" },
                { icon: <Heart size={14} />, label: "Resting HR", value: "58 bpm" },
                { icon: <Thermometer size={14} />, label: "Skin temp", value: "+0.2°C" },
              ].map(({ icon, label, value }) => (
                <div key={label} className="flex items-start gap-3">
                  <span style={{ color: "var(--accent-primary)", marginTop: 2 }}>{icon}</span>
                  <div>
                    <div className="text-xs text-[var(--text-secondary)]">{label}</div>
                    <div className="text-sm" style={{ color: "var(--text-primary)" }}>{value}</div>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-[var(--text-secondary)] mt-6 italic">
              This context shapes every answer.
            </p>
          </GlassCard>
        </div>
      </div>
    </Layout>
  );
}
