import { createFileRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";
import { GlassCard, LabelCaps } from "@/components/GlassCard";
import { Bluetooth, Battery, Lock, Download, Trash2, Bell, Palette, Globe } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Novara" },
      { name: "description", content: "Manage your Novara devices, privacy, notifications, and preferences." },
    ],
  }),
  component: SettingsPage,
});

function Toggle({ on = true }: { on?: boolean }) {
  const { mode } = useTheme();
  const activeColor = mode === "day" ? "var(--accent-primary)" : "var(--accent-primary)";
  return (
    <span className="relative inline-block w-10 h-6 rounded-full transition" style={{
      background: on ? activeColor : "var(--border-subtle)",
    }}>
      <span className="absolute top-0.5 w-5 h-5 rounded-full transition-all" style={{
        background: on ? (mode === "day" ? "#FAF7F4" : "#060E1A") : "var(--text-secondary)",
        left: on ? "auto" : 2,
        right: on ? 2 : "auto",
      }} />
    </span>
  );
}

function SettingsPage() {
  const { mode } = useTheme();

  return (
    <Layout>
      <div className="fade-in-up">
        <LabelCaps>Settings</LabelCaps>
        <h1 className="mt-2 mb-8">Your Novara, your rules</h1>

        <div className="grid lg:grid-cols-2 gap-6 mb-6">
          {/* ── Devices ── */}
          <GlassCard>
            <div className="flex items-center gap-2 mb-4">
              <Bluetooth size={18} style={{ color: "var(--accent-primary)" }} />
              <LabelCaps>Your devices</LabelCaps>
            </div>
            <div className="space-y-3">
              <div className="p-4 rounded-2xl" style={{
                background: mode === "day" ? "rgba(192,132,109,0.06)" : "rgba(79,209,197,0.06)",
                border: `1px solid ${mode === "day" ? "rgba(192,132,109,0.2)" : "rgba(79,209,197,0.2)"}`,
              }}>
                <div className="flex justify-between items-center">
                  <div>
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>Novara Ring</div>
                    <div className="text-xs text-[var(--text-secondary)]">Connected · Synced just now</div>
                  </div>
                  <div className="flex items-center gap-1 text-sm" style={{ color: "var(--text-primary)" }}>
                    <Battery size={14} /> 84%
                  </div>
                </div>
              </div>
              <div className="p-4 rounded-2xl" style={{
                background: mode === "day" ? "rgba(192,132,109,0.03)" : "rgba(79,209,197,0.03)",
                border: `1px solid ${mode === "day" ? "rgba(192,132,109,0.10)" : "rgba(79,209,197,0.10)"}`,
              }}>
                <div className="flex justify-between items-center">
                  <div>
                    <div className="font-medium" style={{ color: "var(--text-primary)" }}>Novara Band</div>
                    <div className="text-xs text-[var(--text-secondary)]">Firmware v2.1 · Connected</div>
                  </div>
                  <div className="flex items-center gap-1 text-sm" style={{ color: "var(--text-primary)" }}>
                    <Battery size={14} /> 72%
                  </div>
                </div>
              </div>
              <button className="btn-glass text-sm w-full mt-2">+ Add device</button>
            </div>
          </GlassCard>

          {/* ── Privacy ── */}
          <GlassCard>
            <div className="flex items-center gap-2 mb-4">
              <Lock size={18} style={{ color: "var(--accent-primary)" }} />
              <LabelCaps>Privacy & Data</LabelCaps>
            </div>
            <div className="space-y-4">
              {[
                ["On-device processing", "Your data never leaves your device", true],
                ["Anonymous research", "Share aggregated, anonymized data", false],
                ["Encrypted backup", "End-to-end encrypted cloud sync", true],
              ].map(([k, d, on]) => (
                <div key={k as string} className="flex justify-between items-center">
                  <div>
                    <div className="text-sm" style={{ color: "var(--text-primary)" }}>{k as string}</div>
                    <div className="text-xs text-[var(--text-secondary)]">{d as string}</div>
                  </div>
                  <Toggle on={on as boolean} />
                </div>
              ))}
            </div>
            <div className="mt-6 flex gap-2">
              <button className="btn-glass flex items-center gap-2 text-sm">
                <Download size={14} /> Export
              </button>
              <button className="btn-glass flex items-center gap-2 text-sm" style={{ color: mode === "day" ? "#C06D6D" : "#FC8181" }}>
                <Trash2 size={14} /> Delete all
              </button>
            </div>
            <p className="text-xs text-[var(--text-secondary)] mt-4 italic">
              Your raw health data stays on your device, always.
            </p>
          </GlassCard>
        </div>

        <div className="grid lg:grid-cols-2 gap-6">
          {/* ── Notifications ── */}
          <GlassCard>
            <div className="flex items-center gap-2 mb-4">
              <Bell size={18} style={{ color: "var(--accent-primary)" }} />
              <LabelCaps>Notifications</LabelCaps>
            </div>
            <div className="space-y-4">
              {[
                ["Recovery alerts", true],
                ["Sleep reminders", true],
                ["HRV anomaly alerts", false],
                ["Activity goals", true],
                ["Low battery", true],
              ].map(([k, on]) => (
                <div key={k as string} className="flex justify-between items-center text-sm">
                  <span style={{ color: "var(--text-primary)" }}>{k as string}</span>
                  <Toggle on={on as boolean} />
                </div>
              ))}
            </div>
          </GlassCard>

          {/* ── Preferences ── */}
          <GlassCard>
            <div className="flex items-center gap-2 mb-4">
              <Palette size={18} style={{ color: "var(--accent-primary)" }} />
              <LabelCaps>Preferences</LabelCaps>
            </div>
            <div className="space-y-4 text-sm">
              <div className="flex justify-between items-center">
                <span style={{ color: "var(--text-primary)" }}>Theme</span>
                <span className="phase-pill">
                  {mode === "day" ? "☀️ Dawn" : "🌙 Night"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span style={{ color: "var(--text-primary)" }}>Units</span>
                <span className="text-[var(--text-secondary)]">Metric (°C, kg)</span>
              </div>
              <div className="flex justify-between items-center">
                <span style={{ color: "var(--text-primary)" }}>Language</span>
                <select className="bg-transparent text-sm border rounded-lg px-2 py-1" style={{
                  borderColor: "var(--border-subtle)",
                  color: "var(--accent-primary)",
                  background: "var(--glass-bg)",
                }}>
                  <option style={{ background: "var(--bg-deep)" }}>English</option>
                  <option style={{ background: "var(--bg-deep)" }}>Hindi</option>
                </select>
              </div>
              <div className="flex justify-between items-center">
                <span style={{ color: "var(--text-primary)" }}>Step goal</span>
                <span className="text-[var(--text-secondary)]">10,000 steps</span>
              </div>
              <div className="flex justify-between items-center">
                <span style={{ color: "var(--text-primary)" }}>Sleep goal</span>
                <span className="text-[var(--text-secondary)]">8 hours</span>
              </div>
            </div>
          </GlassCard>
        </div>

        <p className="text-center text-xs text-[var(--text-secondary)] mt-12 italic">
          Novara · v1.0 · Built with precision.
        </p>
      </div>
    </Layout>
  );
}
