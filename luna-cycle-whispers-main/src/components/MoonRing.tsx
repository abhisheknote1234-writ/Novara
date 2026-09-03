import { useTheme } from "@/context/ThemeContext";

interface Props {
  day: number;
  cycleLength?: number;
  size?: number;
  phase?: string;
  emoji?: string;
}

export function MoonRing({ day, cycleLength = 28, size = 200, phase = "Luteal", emoji = "🌖" }: Props) {
  const { mode } = useTheme();
  const progress = day / cycleLength;
  const r = size / 2 - 12;
  const c = 2 * Math.PI * r;
  const dash = c * progress;

  // Calming gradients
  // Day: Rich Sakura Pink / Wisteria
  // Night: Bioluminescent Teal / Ocean Blue
  const gradColors = mode === "day"
    ? { c1: "#D4868E", c2: "#C4A4CC", c3: "#B088B0", c4: "#E8B8A0" }
    : { c1: "#81E6D9", c2: "#4FD1C5", c3: "#63B3ED", c4: "#38A89D" };

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="relative slow-rotate" style={{ animationDuration: "180s" }}>
        <defs>
          <linearGradient id={`ring-grad-${size}-${mode}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={gradColors.c1} />
            <stop offset="35%" stopColor={gradColors.c2} />
            <stop offset="70%" stopColor={gradColors.c3} />
            <stop offset="100%" stopColor={gradColors.c4} />
          </linearGradient>
        </defs>
        
        {/* Minimal thin background track */}
        <circle 
          cx={size/2} cy={size/2} r={r} 
          fill="none" 
          stroke="var(--border-subtle)" 
          strokeWidth="1.5" 
        />
        
        {/* Inner delicate dashed track */}
        <circle 
          cx={size/2} cy={size/2} r={r - 12} 
          fill="none" 
          stroke="var(--border-subtle)" 
          strokeWidth="0.5" 
          strokeDasharray="1 8" 
        />
        
        {/* Progress arc (no neon glow, just elegant gradient) */}
        <circle
          cx={size/2} cy={size/2} r={r}
          fill="none"
          stroke={`url(#ring-grad-${size}-${mode})`}
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          transform={`rotate(-90 ${size/2} ${size/2})`}
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div style={{ fontSize: size * 0.18, opacity: 0.9 }}>{emoji}</div>
        <div className="font-display" style={{
          fontSize: size * 0.22,
          fontFamily: "var(--font-display)",
          fontWeight: 300,
          lineHeight: 1,
          marginTop: "6px",
          color: "var(--text-primary)",
        }}>
          {day}
        </div>
        <div className="label-caps mt-2" style={{ fontSize: 9, letterSpacing: 3 }}>{phase}</div>
      </div>
    </div>
  );
}
