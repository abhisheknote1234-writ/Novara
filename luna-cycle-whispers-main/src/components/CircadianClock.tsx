import { useState } from "react";
import { useTheme } from "@/context/ThemeContext";
import { GlassCard, LabelCaps } from "./GlassCard";
import { Sun, Moon, Zap, Volume2, VolumeX, Sparkles, Clock, AlertTriangle } from "lucide-react";

export function CircadianClock() {
  const { mode } = useTheme();
  const [activeWindow, setActiveWindow] = useState<number>(0);
  const [isPlayingAudio, setIsPlayingAudio] = useState<boolean>(false);

  const CIRCADIAN_WINDOWS = [
    {
      time: "06:30 AM",
      title: "Core Temperature Rise",
      desc: "Cortisol awakening response begins. Ideal window for natural sunlight exposure.",
      type: "light",
      icon: Sun,
    },
    {
      time: "10:00 AM — 01:30 PM",
      title: "Peak Cognitive Focus",
      desc: "Maximum autonomic stability & reaction speed. Ideal window for deep work & complex tasks.",
      type: "focus",
      icon: Zap,
    },
    {
      time: "05:00 PM — 07:00 PM",
      title: "Peak Cardiovascular Efficiency",
      desc: "Highest muscle strength & body temperature peak. Ideal window for high-intensity physical activity.",
      type: "workout",
      icon: Sparkles,
    },
    {
      time: "09:30 PM",
      title: "Melatonin Onset Window",
      desc: "Dim-light melatonin onset (DLMO). Recommended to reduce blue light exposure to prime sleep pressure.",
      type: "sleep",
      icon: Moon,
    },
  ];

  return (
    <GlassCard className="p-6 md:p-8 my-8" hover={false}>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Clock size={16} style={{ color: "var(--accent-primary)" }} />
            <LabelCaps>Circadian Alignment Engine</LabelCaps>
          </div>
          <h2 style={{ fontSize: 24, margin: 0 }}>Biological Rhythm & Chronotype Matrix</h2>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setIsPlayingAudio(!isPlayingAudio)}
            className="px-3.5 py-2 rounded-xl text-xs flex items-center gap-2 transition-all btn-glass"
          >
            {isPlayingAudio ? <VolumeX size={14} /> : <Volume2 size={14} />}
            {isPlayingAudio ? "Mute Delta Waves" : "Play Sleep Soundscape"}
          </button>
        </div>
      </div>

      {/* Sleep Debt & Chronotype Summary Header */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <div className="p-4 rounded-2xl" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
          <LabelCaps>Chronotype Profile</LabelCaps>
          <div className="font-display text-xl mt-1" style={{ color: "var(--text-primary)" }}>
            Early Lark <span className="text-xs text-[var(--text-secondary)] font-sans">88% Match</span>
          </div>
          <div className="text-xs text-[var(--text-secondary)] mt-1">Optimal Sleep Window: 10:15 PM</div>
        </div>

        <div className="p-4 rounded-2xl" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
          <LabelCaps>Current Sleep Debt</LabelCaps>
          <div className="font-display text-xl mt-1 text-emerald-400">
            -22 min <span className="text-xs text-[var(--text-secondary)] font-sans">Surplus</span>
          </div>
          <div className="text-xs text-[var(--text-secondary)] mt-1">Fully Recovered Bank</div>
        </div>

        <div className="p-4 rounded-2xl" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
          <LabelCaps>Melatonin Onset Target</LabelCaps>
          <div className="font-display text-xl mt-1" style={{ color: "var(--accent-primary)" }}>
            09:45 PM
          </div>
          <div className="text-xs text-[var(--text-secondary)] mt-1">Dim lights at 09:00 PM</div>
        </div>

        <div className="p-4 rounded-2xl" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
          <LabelCaps>Temperature Minimum</LabelCaps>
          <div className="font-display text-xl mt-1" style={{ color: "var(--text-primary)" }}>
            04:30 AM
          </div>
          <div className="text-xs text-[var(--text-secondary)] mt-1">Lowest metabolic rate</div>
        </div>
      </div>

      {/* Interactive Circadian Timeline Track */}
      <LabelCaps>24-Hour Circadian Phase Windows</LabelCaps>
      <div className="grid md:grid-cols-4 gap-4 mt-3">
        {CIRCADIAN_WINDOWS.map((win, idx) => {
          const isSelected = activeWindow === idx;
          const IconComponent = win.icon;
          return (
            <div
              key={win.title}
              onClick={() => setActiveWindow(idx)}
              className="p-5 rounded-2xl cursor-pointer transition-all duration-300 relative overflow-hidden"
              style={{
                background: isSelected ? "var(--glass-bg)" : "transparent",
                border: `1.5px solid ${isSelected ? "var(--accent-primary)" : "var(--border-subtle)"}`,
                boxShadow: isSelected ? "var(--shadow-soft)" : "none",
              }}
            >
              {isSelected && (
                <div className="absolute top-0 left-0 right-0 h-1 bg-[var(--accent-primary)]" />
              )}
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-mono font-medium px-2 py-0.5 rounded-md"
                  style={{
                    background: isSelected ? "var(--accent-primary)" : "var(--border-subtle)",
                    color: isSelected ? (mode === "day" ? "#FFF" : "#060E1A") : "var(--text-secondary)",
                  }}
                >
                  {win.time}
                </span>
                <IconComponent size={16} style={{ color: isSelected ? "var(--accent-primary)" : "var(--text-secondary)" }} />
              </div>
              <h4 className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)", margin: 0 }}>
                {win.title}
              </h4>
              <p className="text-xs text-[var(--text-secondary)] mt-2 leading-relaxed">
                {win.desc}
              </p>
            </div>
          );
        })}
      </div>

      {/* Audio Soundscape Player Banner if active */}
      {isPlayingAudio && (
        <div className="mt-6 p-4 rounded-2xl flex items-center justify-between fade-in-up"
          style={{
            background: mode === "day" ? "rgba(192,132,109,0.12)" : "rgba(79,209,197,0.12)",
            border: "1px solid var(--accent-primary)",
          }}
        >
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full bg-[var(--accent-primary)] animate-ping" />
            <div>
              <div className="text-xs font-medium text-[var(--text-primary)]">
                Playing: 432Hz Pink Noise + Isochronic Delta Waves
              </div>
              <div className="text-[11px] text-[var(--text-secondary)]">
                Designed to entrain brainwaves into deep stage 3 slow-wave sleep.
              </div>
            </div>
          </div>
          {/* Animated sound wave bars */}
          <div className="flex items-end gap-1 h-6">
            {[40, 80, 50, 90, 60, 100, 70, 45].map((h, i) => (
              <span
                key={i}
                className="w-1 bg-[var(--accent-primary)] rounded-full animate-bounce"
                style={{ height: `${h}%`, animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
