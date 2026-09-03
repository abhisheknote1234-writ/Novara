import { useState } from "react";
import { useTheme } from "@/context/ThemeContext";
import { GlassCard, LabelCaps } from "./GlassCard";
import { Check, Info, Sparkles, Shield, Cpu } from "lucide-react";

interface Finish {
  id: string;
  name: string;
  color: string;
  grad: string;
  accent: string;
  description: string;
}

const FINISHES: Finish[] = [
  {
    id: "rose-copper",
    name: "Rose Copper",
    color: "#C0846D",
    grad: "linear-gradient(135deg, #E8B8A0 0%, #C0846D 50%, #8A5A48 100%)",
    accent: "#D4A98A",
    description: "Aerospace-grade titanium coated with warm rose-copper PVD finish.",
  },
  {
    id: "signal-teal",
    name: "Signal Teal",
    color: "#4FD1C5",
    grad: "linear-gradient(135deg, #81E6D9 0%, #4FD1C5 50%, #1A756C 100%)",
    accent: "#63B3ED",
    description: "Anodized titanium with bioluminescent micro-polished accent ring.",
  },
  {
    id: "matte-obsidian",
    name: "Matte Obsidian",
    color: "#2D3748",
    grad: "linear-gradient(135deg, #4A5568 0%, #2D3748 50%, #1A202C 100%)",
    accent: "#A0AEC0",
    description: "Diamond-like carbon (DLC) coating for scratch resistance and covert stealth.",
  },
  {
    id: "stellar-gold",
    name: "Stellar Gold",
    color: "#D69E2E",
    grad: "linear-gradient(135deg, #F6E05E 0%, #D69E2E 50%, #744210 100%)",
    accent: "#ECC94B",
    description: "18k gold physical vapor deposition with surgical stainless substrate.",
  },
];

const SENSOR_HOTSPOTS = [
  {
    id: "ppg",
    name: "Quad-Channel Optical PPG",
    pos: { cx: 240, cy: 90 },
    desc: "Dual green & infrared LEDs capturing arterial pulse waveform at 250Hz sample rate.",
  },
  {
    id: "temp",
    name: "NTC Skin Temp Thermistor",
    pos: { cx: 170, cy: 170 },
    desc: "Medical-grade temperature sensor detecting 0.05°C subtle skin delta.",
  },
  {
    id: "accel",
    name: "3D Motion Accelerometer",
    pos: { cx: 310, cy: 170 },
    desc: "Low-power 6-axis IMU tracking sleep toss-and-turns and micro-movements.",
  },
  {
    id: "eda",
    name: "Galvanic Skin Response (EDA)",
    pos: { cx: 240, cy: 250 },
    desc: "Continuous micro-sweat conductivity tracking real-time sympathetic stress responses.",
  },
];

export function WearableCustomizer() {
  const { mode } = useTheme();
  const [selectedFinish, setSelectedFinish] = useState<Finish>(FINISHES[0]);
  const [activeHotspot, setActiveHotspot] = useState<typeof SENSOR_HOTSPOTS[0] | null>(SENSOR_HOTSPOTS[0]);
  const [ringSize, setRingSize] = useState<number>(9);

  return (
    <GlassCard className="p-6 md:p-10 my-8" hover={false}>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-8">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles size={16} style={{ color: "var(--accent-primary)" }} />
            <LabelCaps>Interactive Studio</LabelCaps>
          </div>
          <h2 style={{ fontSize: 26, margin: 0 }}>Configure Your Novara Ring</h2>
          <p className="text-sm text-[var(--text-secondary)] mt-1">
            Explore industrial design materials, optical sensor architecture, and precision fit sizing.
          </p>
        </div>
        <div className="phase-pill">
          <span className="w-2 h-2 rounded-full" style={{ background: selectedFinish.color }} />
          <span>{selectedFinish.name} Edition</span>
        </div>
      </div>

      <div className="grid lg:grid-cols-12 gap-8 items-center">
        {/* Visual Ring Display */}
        <div className="lg:col-span-7 flex flex-col items-center justify-center relative min-h-[340px] rounded-3xl p-6 overflow-hidden"
          style={{
            background: mode === "day"
              ? "radial-gradient(circle at 50% 50%, rgba(245,240,235,0.9) 0%, rgba(235,225,215,0.5) 100%)"
              : "radial-gradient(circle at 50% 50%, rgba(15,28,48,0.9) 0%, rgba(6,14,26,0.95) 100%)",
            border: "1px solid var(--border-subtle)",
          }}
        >
          {/* Background Ambient Glow */}
          <div
            className="absolute rounded-full pointer-events-none transition-all duration-700"
            style={{
              width: 260,
              height: 260,
              background: `radial-gradient(circle, ${selectedFinish.color}40 0%, transparent 70%)`,
              filter: "blur(40px)",
            }}
          />

          {/* SVG 3D-Look Ring */}
          <svg viewBox="0 0 480 340" className="w-full max-w-[420px] relative z-10">
            <defs>
              <linearGradient id="ring-finish-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor={selectedFinish.color} stopOpacity="1" />
                <stop offset="50%" stopColor={selectedFinish.accent} stopOpacity="0.9" />
                <stop offset="100%" stopColor="#1A202C" stopOpacity="0.8" />
              </linearGradient>
              <filter id="sensor-glow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Outer Ring Torus */}
            <ellipse cx="240" cy="170" rx="140" ry="100" fill="none" stroke="url(#ring-finish-grad)" strokeWidth="32" />
            <ellipse cx="240" cy="170" rx="124" ry="84" fill="none" stroke="rgba(0,0,0,0.25)" strokeWidth="6" />
            <ellipse cx="240" cy="170" rx="108" ry="68" fill="none" stroke="url(#ring-finish-grad)" strokeWidth="10" opacity="0.6" />

            {/* Specular Metallic Highlight */}
            <path d="M 120 170 A 140 100 0 0 1 240 70" fill="none" stroke="#FFFFFF" strokeWidth="4" opacity="0.4" strokeLinecap="round" />
            <path d="M 240 70 A 140 100 0 0 1 360 170" fill="none" stroke={selectedFinish.accent} strokeWidth="2" opacity="0.6" />

            {/* Sensor Pod Hotspots */}
            {SENSOR_HOTSPOTS.map((hs) => {
              const isSelected = activeHotspot?.id === hs.id;
              return (
                <g key={hs.id} onClick={() => setActiveHotspot(hs)} className="cursor-pointer">
                  <circle
                    cx={hs.pos.cx}
                    cy={hs.pos.cy}
                    r={isSelected ? "14" : "10"}
                    fill={isSelected ? "var(--accent-primary)" : selectedFinish.color}
                    opacity={isSelected ? "0.9" : "0.7"}
                    className="transition-all duration-300"
                    filter="url(#sensor-glow)"
                  />
                  <circle
                    cx={hs.pos.cx}
                    cy={hs.pos.cy}
                    r="4"
                    fill="#FFFFFF"
                    className={isSelected ? "pulse-glow" : ""}
                  />
                  {isSelected && (
                    <circle
                      cx={hs.pos.cx}
                      cy={hs.pos.cy}
                      r="20"
                      fill="none"
                      stroke="var(--accent-primary)"
                      strokeWidth="1.5"
                      strokeDasharray="3 3"
                      className="slow-rotate"
                    />
                  )}
                </g>
              );
            })}
          </svg>

          {/* Active Sensor Popover Banner */}
          {activeHotspot && (
            <div className="mt-4 p-3 px-5 rounded-2xl text-center max-w-md backdrop-blur-md transition-all fade-in-up"
              style={{
                background: "var(--glass-bg)",
                border: "1px solid var(--border-subtle)",
              }}
            >
              <div className="text-xs font-semibold text-[var(--accent-primary)] uppercase tracking-wider">
                {activeHotspot.name}
              </div>
              <div className="text-xs text-[var(--text-secondary)] mt-1">
                {activeHotspot.desc}
              </div>
            </div>
          )}
        </div>

        {/* Controls Column */}
        <div className="lg:col-span-5 flex flex-col gap-6">
          {/* Finish Picker */}
          <div>
            <LabelCaps>Select Finish</LabelCaps>
            <div className="grid grid-cols-2 gap-3 mt-3">
              {FINISHES.map((f) => {
                const active = selectedFinish.id === f.id;
                return (
                  <button
                    key={f.id}
                    onClick={() => setSelectedFinish(f)}
                    className="p-3.5 rounded-2xl flex items-center gap-3 transition-all text-left"
                    style={{
                      background: active ? "var(--glass-bg)" : "transparent",
                      border: `1.5px solid ${active ? "var(--accent-primary)" : "var(--border-subtle)"}`,
                      boxShadow: active ? "var(--shadow-soft)" : "none",
                    }}
                  >
                    <span
                      className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 shadow-sm"
                      style={{ background: f.grad }}
                    >
                      {active && <Check size={12} className="text-white stroke-[3]" />}
                    </span>
                    <div>
                      <div className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{f.name}</div>
                    </div>
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-[var(--text-secondary)] mt-3 italic">
              {selectedFinish.description}
            </p>
          </div>

          {/* Ring Sizer Slider */}
          <div className="pt-4 border-t" style={{ borderColor: "var(--border-subtle)" }}>
            <div className="flex justify-between items-center mb-2">
              <LabelCaps>Precision Ring Size</LabelCaps>
              <span className="font-display text-lg" style={{ color: "var(--text-primary)" }}>
                US {ringSize}
              </span>
            </div>
            <input
              type="range"
              min="6"
              max="13"
              step="1"
              value={ringSize}
              onChange={(e) => setRingSize(Number(e.target.value))}
              className="w-full h-2 rounded-lg appearance-none cursor-pointer"
              style={{ accentColor: "var(--accent-primary)" }}
            />
            <div className="flex justify-between text-[11px] text-[var(--text-secondary)] mt-2">
              <span>Size 6 (16.5mm)</span>
              <span>Size 9 (19.0mm)</span>
              <span>Size 13 (22.2mm)</span>
            </div>
          </div>

          {/* Specs Checklist */}
          <div className="p-4 rounded-2xl space-y-2.5" style={{ background: "var(--glass-bg)", border: "1px solid var(--border-subtle)" }}>
            <div className="flex items-center gap-2 text-xs text-[var(--text-primary)] font-medium">
              <Shield size={14} className="text-[var(--accent-primary)]" />
              100m Water Resistance (10 ATM)
            </div>
            <div className="flex items-center gap-2 text-xs text-[var(--text-primary)] font-medium">
              <Cpu size={14} className="text-[var(--accent-primary)]" />
              7-Day Ultra-low Power Battery Architecture
            </div>
            <div className="flex items-center gap-2 text-xs text-[var(--text-primary)] font-medium">
              <Info size={14} className="text-[var(--accent-primary)]" />
              Hypoallergenic Titanium Inner Band Molding
            </div>
          </div>
        </div>
      </div>
    </GlassCard>
  );
}
