import { useEffect, useState, useMemo } from "react";
import { useTheme } from "@/context/ThemeContext";

/* ═══════════════════════════════════════════
   NOVARA ATMOSPHERE — Micro-particles & Signal Glow
   ═══════════════════════════════════════════ */

// Day mode: warm copper/gold micro-dust colors
const dayParticleColors = [
  "rgba(192, 132, 109, 0.50)", // Copper
  "rgba(212, 169, 138, 0.45)", // Light copper
  "rgba(168, 149, 133, 0.40)", // Stone
  "rgba(138, 126, 114, 0.35)", // Muted stone
];

export function DreamyAtmosphere() {
  const { mode } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  /* ☀️ Day: Floating copper/gold micro-particles */
  const particles = useMemo(() => {
    return Array.from({ length: 30 }, () => {
      const size = 2 + Math.random() * 4;
      const dx = (Math.random() - 0.5) * 80;
      const dy = -(60 + Math.random() * 40); // float upward

      return {
        left: Math.random() * 100,
        top: 20 + Math.random() * 80, // start from lower portions
        size,
        duration: 18 + Math.random() * 22,
        delay: Math.random() * 20,
        opacity: 0.3 + Math.random() * 0.4,
        colorIdx: Math.floor(Math.random() * dayParticleColors.length),
        customCSS: {
          "--particle-dx": `${dx}px`,
          "--particle-dy": `${dy}vh`,
        } as React.CSSProperties,
      };
    });
  }, []);

  /* 🌙 Night: Bioluminescent particles (float upward) */
  const plankton = useMemo(() => {
    return Array.from({ length: 40 }, () => ({
      left: Math.random() * 100,
      bottom: Math.random() * 100,
      size: 1 + Math.random() * 3,
      riseDur: 15 + Math.random() * 25,
      blinkDur: 2 + Math.random() * 5,
      delay: Math.random() * 18,
      driftX: (Math.random() - 0.5) * 60,
      hue: Math.random() > 0.6 ? "blue" : "teal",
    }));
  }, []);

  /* 🌙 Night: Glowing fog waves */
  const fogWaves = useMemo(() => {
    return Array.from({ length: 4 }, (_, i) => ({
      y: 55 + i * 12,
      duration: 18 + i * 6,
      delay: i * 3,
      opacity: 0.08 + (3 - i) * 0.03,
      height: 25 + i * 8,
    }));
  }, []);

  if (!mounted) return null;

  return (
    <>
      {/* ═══ DAY: Warm Copper Atmosphere ═══ */}
      {mode === "day" && (
        <>
          {/* Warm light source */}
          <div
            className="celestial-orb"
            style={{
              top: "-5%",
              right: "5%",
              width: 350,
              height: 350,
              background: "radial-gradient(circle, rgba(212,169,138,0.65) 0%, rgba(192,132,109,0.25) 35%, rgba(168,149,133,0.08) 60%, transparent 75%)",
            }}
          />

          {/* Lower fog layer 1 */}
          <div className="fog-layer" style={{
            bottom: "0%", height: "35%",
            background: "linear-gradient(0deg, rgba(192,132,109,0.08) 0%, rgba(168,149,133,0.04) 40%, transparent 100%)",
            animationDuration: "22s",
            animationDelay: "0s",
          }} />
          {/* Lower fog layer 2 */}
          <div className="fog-layer" style={{
            bottom: "5%", height: "30%",
            background: "linear-gradient(0deg, rgba(212,169,138,0.06) 0%, rgba(192,132,109,0.03) 50%, transparent 100%)",
            animationDuration: "30s",
            animationDelay: "-8s",
          }} />

          {/* Upper atmospheric haze */}
          <div className="atmosphere-layer" style={{
            top: 0, left: 0, width: "100%", height: "100vh",
            background: "linear-gradient(135deg, rgba(192,132,109,0.08) 0%, rgba(138,126,114,0.04) 40%, transparent 100%)",
            animationDuration: "18s",
          }} />

          {/* Floating micro-particles */}
          {particles.map((p, i) => (
            <div
              key={`particle-${i}`}
              className="micro-particle"
              style={{
                left: `${p.left}%`,
                top: `${p.top}%`,
                width: p.size,
                height: p.size,
                opacity: p.opacity,
                background: dayParticleColors[p.colorIdx],
                boxShadow: `0 0 ${p.size * 2}px ${dayParticleColors[p.colorIdx]}`,
                animationDuration: `${p.duration}s`,
                animationDelay: `${p.delay}s`,
                ...p.customCSS,
              }}
            />
          ))}
        </>
      )}

      {/* ═══ NIGHT: Signal Glow Atmosphere ═══ */}
      {mode === "night" && (
        <>
          {/* Teal signal orb */}
          <div
            className="celestial-orb"
            style={{
              top: "3%",
              right: "12%",
              width: 180,
              height: 180,
              background: "radial-gradient(circle, rgba(129,230,217,0.7) 0%, rgba(79,209,197,0.25) 40%, rgba(56,168,157,0.08) 65%, transparent 85%)",
              filter: "blur(5px)",
            }}
          />
          {/* Ambient light rays */}
          <div className="atmosphere-layer" style={{
            top: 0, right: 0, width: "60%", height: "60vh",
            background: "radial-gradient(ellipse at 80% 10%, rgba(129,230,217,0.06) 0%, rgba(79,209,197,0.02) 40%, transparent 70%)",
            animationDuration: "15s",
          }} />

          {/* Fog waves */}
          {fogWaves.map((fw, i) => (
            <div
              key={`fog-${i}`}
              className="fog-layer"
              style={{
                bottom: `${100 - fw.y - fw.height}%`,
                height: `${fw.height}%`,
                background: `linear-gradient(0deg, rgba(79,209,197,${fw.opacity}) 0%, rgba(56,168,157,${fw.opacity * 0.4}) 40%, transparent 100%)`,
                animationDuration: `${fw.duration}s`,
                animationDelay: `${-fw.delay}s`,
              }}
            />
          ))}

          {/* Upper glow */}
          <div className="fog-layer" style={{
            top: "0%", height: "25%",
            background: "linear-gradient(180deg, rgba(79,209,197,0.04) 0%, rgba(99,179,237,0.02) 50%, transparent 100%)",
            animationDuration: "35s",
            animationDelay: "-5s",
          }} />

          {/* Bioluminescent plankton */}
          {plankton.map((p, i) => (
            <div
              key={`plankton-${i}`}
              className="plankton"
              style={{
                left: `${p.left}%`,
                bottom: `${p.bottom}%`,
                width: p.size,
                height: p.size,
                animationDuration: `${p.riseDur}s, ${p.blinkDur}s`,
                animationDelay: `${p.delay}s, ${p.delay * 0.7}s`,
                "--plankton-drift": `${p.driftX}px`,
                background: p.hue === "blue"
                  ? "#90CDF4"
                  : "#81E6D9",
                boxShadow: p.hue === "blue"
                  ? `0 0 ${p.size * 4}px ${p.size * 1.5}px rgba(99,179,237,0.5), 0 0 ${p.size * 12}px ${p.size * 3}px rgba(99,179,237,0.12)`
                  : `0 0 ${p.size * 4}px ${p.size * 1.5}px rgba(79,209,197,0.5), 0 0 ${p.size * 12}px ${p.size * 3}px rgba(79,209,197,0.12)`,
              } as React.CSSProperties}
            />
          ))}
        </>
      )}
    </>
  );
}
