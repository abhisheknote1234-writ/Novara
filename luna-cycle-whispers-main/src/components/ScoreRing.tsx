import { useTheme } from "@/context/ThemeContext";

interface Props {
  score: number;
  maxScore?: number;
  label: string;
  sublabel?: string;
  size?: number;
}

/**
 * ScoreRing — Elegant animated score ring for Novara.
 * Displays a numeric score with a gradient progress arc.
 * Used for Sleep Score, Recovery Score, Readiness, etc.
 */
export function ScoreRing({ score, maxScore = 100, label, sublabel, size = 200 }: Props) {
  const { mode } = useTheme();
  const progress = Math.min(score / maxScore, 1);
  const r = size / 2 - 12;
  const c = 2 * Math.PI * r;
  const dash = c * progress;

  const gradColors = mode === "day"
    ? { c1: "#C0846D", c2: "#D4A98A", c3: "#8A7E72", c4: "#A89585" }
    : { c1: "#81E6D9", c2: "#4FD1C5", c3: "#63B3ED", c4: "#38A89D" };

  // Score quality label
  const quality = score >= 85 ? "Excellent" : score >= 70 ? "Good" : score >= 50 ? "Fair" : "Low";

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="relative slow-rotate" style={{ animationDuration: "180s" }}>
        <defs>
          <linearGradient id={`score-grad-${size}-${mode}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={gradColors.c1} />
            <stop offset="35%" stopColor={gradColors.c2} />
            <stop offset="70%" stopColor={gradColors.c3} />
            <stop offset="100%" stopColor={gradColors.c4} />
          </linearGradient>
        </defs>

        {/* Background track */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth="1.5"
        />

        {/* Inner dashed track */}
        <circle
          cx={size / 2} cy={size / 2} r={r - 12}
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth="0.5"
          strokeDasharray="1 8"
        />

        {/* Progress arc */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={`url(#score-grad-${size}-${mode})`}
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>

      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="section-label" style={{ fontSize: 9, letterSpacing: 3 }}>
          {label.toUpperCase()}
        </div>
        <div className="font-display" style={{
          fontSize: size * 0.22,
          fontFamily: "var(--font-display)",
          fontWeight: 300,
          lineHeight: 1,
          marginTop: "6px",
          color: "var(--text-primary)",
        }}>
          {score}
        </div>
        <div className="text-[var(--text-secondary)] mt-2" style={{ fontSize: 10 }}>
          {sublabel || quality}
        </div>
      </div>
    </div>
  );
}
