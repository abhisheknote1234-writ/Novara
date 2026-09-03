import { useState, useEffect } from "react";
import { useTheme } from "@/context/ThemeContext";
import { GlassCard, LabelCaps } from "./GlassCard";
import { Activity, Play, Pause, RefreshCw, Heart, Wind, ShieldAlert, Sliders } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, YAxis, XAxis, Tooltip } from "recharts";

export function LivePulseSimulator() {
  const { mode } = useTheme();
  const [bpm, setBpm] = useState<number>(68);
  const [stress, setStress] = useState<number>(24);
  const [isBreathingActive, setIsBreathingActive] = useState<boolean>(false);
  const [breathPhase, setBreathPhase] = useState<"Inhale" | "Hold" | "Exhale">("Inhale");
  const [breathProgress, setBreathProgress] = useState<number>(0);
  const [arrhythmiaSim, setArrhythmiaSim] = useState<boolean>(false);

  // Generate dynamic PPG pulse wave based on BPM & stress
  const generatePulseData = (currentBpm: number, currentStress: number, hasArrhythmia: boolean) => {
    const points = 100;
    const frequency = (currentBpm / 60) * 4; // Cycles across length
    return Array.from({ length: points }, (_, i) => {
      const t = i / points;
      const beat = Math.sin(t * Math.PI * frequency);
      const systolic = Math.pow(Math.max(0, beat), 3) * 75;
      const dicrotic = Math.pow(Math.max(0, Math.sin(t * Math.PI * frequency + 1.2)), 4) * (25 - currentStress * 0.15);
      const noise = (Math.random() - 0.5) * (currentStress * 0.15);
      const arrhythmiaSpike = hasArrhythmia && i > 40 && i < 55 ? Math.sin(i * 0.8) * 35 : 0;
      const val = 30 + systolic + dicrotic + noise + arrhythmiaSpike;
      return { t: i, val: Math.max(10, Math.min(100, Math.round(val))) };
    });
  };

  const [waveData, setWaveData] = useState(() => generatePulseData(68, 24, false));

  // Auto update waveform on controls change
  useEffect(() => {
    setWaveData(generatePulseData(bpm, stress, arrhythmiaSim));
  }, [bpm, stress, arrhythmiaSim]);

  // Periodic waveform refresh simulation
  useEffect(() => {
    const interval = setInterval(() => {
      setWaveData(generatePulseData(bpm, stress, arrhythmiaSim));
    }, 1200);
    return () => clearInterval(interval);
  }, [bpm, stress, arrhythmiaSim]);

  // Breathing pacer timer
  useEffect(() => {
    if (!isBreathingActive) return;

    let timer: NodeJS.Timeout;
    const cycleDuration = 12; // 4s Inhale, 4s Hold, 4s Exhale
    let elapsed = 0;

    const interval = setInterval(() => {
      elapsed = (elapsed + 0.1) % cycleDuration;
      setBreathProgress((elapsed / cycleDuration) * 100);

      if (elapsed < 4) {
        setBreathPhase("Inhale");
      } else if (elapsed < 8) {
        setBreathPhase("Hold");
      } else {
        setBreathPhase("Exhale");
      }
    }, 100);

    return () => clearInterval(interval);
  }, [isBreathingActive]);

  const t = mode === "day" ? {
    stroke: "#C0846D",
    fillTop: "rgba(192, 132, 109, 0.3)",
    fillBot: "rgba(192, 132, 109, 0.0)",
  } : {
    stroke: "#4FD1C5",
    fillTop: "rgba(79, 209, 197, 0.3)",
    fillBot: "rgba(79, 209, 197, 0.0)",
  };

  return (
    <GlassCard className="p-6 md:p-8 my-8" hover={false}>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Activity size={16} style={{ color: "var(--accent-primary)" }} />
            <LabelCaps>Live Bio-Feedback Simulator</LabelCaps>
          </div>
          <h2 style={{ fontSize: 24, margin: 0 }}>Real-Time PPG Signal Studio</h2>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setArrhythmiaSim(!arrhythmiaSim)}
            className="px-3.5 py-1.5 rounded-xl text-xs flex items-center gap-2 transition-all"
            style={{
              background: arrhythmiaSim ? "rgba(239, 68, 68, 0.15)" : "var(--glass-bg)",
              border: `1px solid ${arrhythmiaSim ? "#EF4444" : "var(--border-subtle)"}`,
              color: arrhythmiaSim ? "#EF4444" : "var(--text-secondary)",
            }}
          >
            <ShieldAlert size={14} />
            {arrhythmiaSim ? "Ectopic Pulse Active" : "Simulate Irregularity"}
          </button>
        </div>
      </div>

      {/* Main Waveform Canvas Box */}
      <div className="relative rounded-2xl p-4 mb-6 overflow-hidden"
        style={{
          background: mode === "day" ? "rgba(245,240,235,0.7)" : "rgba(6,14,26,0.8)",
          border: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex justify-between items-center mb-2 px-2">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-[var(--accent-primary)] animate-ping" />
            <span className="text-xs font-mono tracking-wider text-[var(--accent-primary)]">LIVE SENSING: 250Hz</span>
          </div>
          <div className="text-xs text-[var(--text-secondary)] font-mono">
            SNR: {arrhythmiaSim ? "72 dB (Noise detected)" : "94 dB (Clean Signal)"}
          </div>
        </div>

        <div className="h-44">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={waveData} margin={{ top: 10, right: 0, left: -30, bottom: 0 }}>
              <defs>
                <linearGradient id={`live-pulse-fill-${mode}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={t.fillTop} stopOpacity={1} />
                  <stop offset="100%" stopColor={t.fillBot} stopOpacity={1} />
                </linearGradient>
              </defs>
              <YAxis domain={[0, 110]} hide />
              <XAxis dataKey="t" hide />
              <Area
                type="monotone"
                dataKey="val"
                stroke={arrhythmiaSim ? "#EF4444" : t.stroke}
                strokeWidth={2}
                fill={`url(#live-pulse-fill-${mode})`}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Interactive Controls & Breathing Pacer */}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* BPM Slider */}
        <div className="p-4 rounded-2xl" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
          <div className="flex justify-between items-center mb-2">
            <div className="flex items-center gap-2">
              <Heart size={16} className="text-red-400" />
              <LabelCaps>Simulated Heart Rate</LabelCaps>
            </div>
            <span className="font-display text-xl font-medium" style={{ color: "var(--text-primary)" }}>
              {bpm} <span className="text-xs font-sans text-[var(--text-secondary)]">BPM</span>
            </span>
          </div>
          <input
            type="range"
            min="45"
            max="140"
            value={bpm}
            onChange={(e) => setBpm(Number(e.target.value))}
            className="w-full h-2 rounded-lg cursor-pointer"
            style={{ accentColor: "var(--accent-primary)" }}
          />
          <div className="flex justify-between text-[11px] text-[var(--text-secondary)] mt-2">
            <span>45 Deep Rest</span>
            <span>70 Normal</span>
            <span>140 Peak Activity</span>
          </div>
        </div>

        {/* Stress Slider */}
        <div className="p-4 rounded-2xl" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
          <div className="flex justify-between items-center mb-2">
            <div className="flex items-center gap-2">
              <Sliders size={16} style={{ color: "var(--accent-primary)" }} />
              <LabelCaps>Autonomic Stress Index</LabelCaps>
            </div>
            <span className="font-display text-xl font-medium" style={{ color: "var(--text-primary)" }}>
              {stress} <span className="text-xs font-sans text-[var(--text-secondary)]">/ 100</span>
            </span>
          </div>
          <input
            type="range"
            min="5"
            max="95"
            value={stress}
            onChange={(e) => setStress(Number(e.target.value))}
            className="w-full h-2 rounded-lg cursor-pointer"
            style={{ accentColor: "var(--accent-primary)" }}
          />
          <div className="flex justify-between text-[11px] text-[var(--text-secondary)] mt-2">
            <span>Relaxed</span>
            <span>Balanced</span>
            <span>High Stress</span>
          </div>
        </div>

        {/* Guided Breathing Pacer */}
        <div className="p-4 rounded-2xl flex flex-col justify-between" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
          <div className="flex justify-between items-center mb-2">
            <div className="flex items-center gap-2">
              <Wind size={16} className="text-teal-400" />
              <LabelCaps>HRV Bio-Pacer</LabelCaps>
            </div>
            <button
              onClick={() => setIsBreathingActive(!isBreathingActive)}
              className="p-1.5 px-3 rounded-xl text-xs flex items-center gap-1.5 btn-primary"
            >
              {isBreathingActive ? <Pause size={12} /> : <Play size={12} />}
              {isBreathingActive ? "Pause Pacer" : "Start Pacer"}
            </button>
          </div>

          {isBreathingActive ? (
            <div className="flex items-center gap-4 my-2">
              <div className="relative w-12 h-12 flex items-center justify-center">
                <div
                  className="absolute inset-0 rounded-full transition-all duration-300"
                  style={{
                    background: "var(--accent-primary)",
                    opacity: breathPhase === "Inhale" ? 0.8 : breathPhase === "Hold" ? 0.9 : 0.3,
                    transform: `scale(${breathPhase === "Inhale" ? 1.3 : breathPhase === "Hold" ? 1.4 : 0.8})`,
                    filter: "blur(4px)",
                  }}
                />
                <span className="relative z-10 text-xs font-bold text-white uppercase">{breathPhase}</span>
              </div>
              <div className="flex-1">
                <div className="text-xs text-[var(--text-primary)] font-medium mb-1">
                  Respiration Sync: {breathPhase} Phase
                </div>
                <div className="w-full h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                  <div
                    className="h-full bg-[var(--accent-primary)] transition-all duration-100"
                    style={{ width: `${breathProgress}%` }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <p className="text-xs text-[var(--text-secondary)] my-2">
              Synchronize your breathing with light pulse rhythms to stimulate parasympathetic vagal nerve tone.
            </p>
          )}
        </div>
      </div>
    </GlassCard>
  );
}
