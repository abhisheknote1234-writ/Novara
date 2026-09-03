import { useTheme } from "@/context/ThemeContext";

interface Props {
  size?: number;
}

/**
 * WearableRing — Hero SVG component for Novara.
 * Visualizes the wearable as an elegant ring with a PPG waveform trace.
 */
export function WearableRing({ size = 220 }: Props) {
  const { mode } = useTheme();
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 16;
  const c = 2 * Math.PI * r;

  const gradColors = mode === "day"
    ? { c1: "#C0846D", c2: "#D4A98A", c3: "#8A7E72", c4: "#A89585" }
    : { c1: "#81E6D9", c2: "#4FD1C5", c3: "#63B3ED", c4: "#38A89D" };

  // Generate a PPG-like waveform path along the ring
  const wavePoints = 120;
  const waveAmplitude = 6;
  const ppgPath = Array.from({ length: wavePoints }, (_, i) => {
    const angle = (i / wavePoints) * Math.PI * 2 - Math.PI / 2;
    const t = i / wavePoints;
    // Simulate PPG: sharp systolic peak, gradual diastolic descent
    const beat = Math.sin(t * Math.PI * 8);
    const systolic = Math.pow(Math.max(0, beat), 3) * waveAmplitude;
    const dicrotic = Math.pow(Math.max(0, Math.sin(t * Math.PI * 8 + 1.2)), 5) * waveAmplitude * 0.3;
    const wave = systolic + dicrotic;
    const wr = r - wave;
    const x = cx + wr * Math.cos(angle);
    const y = cy + wr * Math.sin(angle);
    return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");

  return (
    <div className="relative gentle-float" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="slow-rotate" style={{ animationDuration: "240s" }}>
        <defs>
          <linearGradient id={`wr-grad-${mode}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={gradColors.c1} />
            <stop offset="35%" stopColor={gradColors.c2} />
            <stop offset="70%" stopColor={gradColors.c3} />
            <stop offset="100%" stopColor={gradColors.c4} />
          </linearGradient>
          <filter id="wr-glow">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Outer track */}
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--border-subtle)" strokeWidth="1" />

        {/* Inner dashed track */}
        <circle cx={cx} cy={cy} r={r - 14} fill="none" stroke="var(--border-subtle)" strokeWidth="0.5" strokeDasharray="1 10" />

        {/* Progress ring — 75% fill */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke={`url(#wr-grad-${mode})`}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray={`${c * 0.75} ${c}`}
          transform={`rotate(-90 ${cx} ${cy})`}
        />

        {/* PPG waveform trace */}
        <path
          d={ppgPath}
          fill="none"
          stroke={`url(#wr-grad-${mode})`}
          strokeWidth="1.2"
          opacity="0.5"
          filter="url(#wr-glow)"
        />

        {/* Tiny sensing dots */}
        {[0, 60, 120, 180, 240, 300].map((deg) => {
          const angle = (deg * Math.PI) / 180;
          const dr = r + 4;
          return (
            <circle
              key={deg}
              cx={cx + dr * Math.cos(angle)}
              cy={cy + dr * Math.sin(angle)}
              r="1.5"
              fill={gradColors.c1}
              opacity="0.4"
            />
          );
        })}
      </svg>

      {/* Center content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="section-label" style={{ fontSize: 9, letterSpacing: 3 }}>
          SENSING
        </div>
        <div className="font-display mt-1" style={{
          fontSize: size * 0.13,
          fontFamily: "var(--font-display)",
          fontWeight: 300,
          lineHeight: 1,
          color: "var(--text-primary)",
        }}>
          Active
        </div>
        <div className="text-[var(--text-secondary)] mt-2" style={{ fontSize: 10 }}>
          continuous · 24/7
        </div>
      </div>
    </div>
  );
}
