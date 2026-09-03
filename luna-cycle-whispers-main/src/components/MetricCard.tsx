import { type ReactNode } from "react";
import { GlassCard, LabelCaps } from "./GlassCard";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { useTheme } from "@/context/ThemeContext";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface MetricCardProps {
  icon: ReactNode;
  label: string;
  value: string;
  unit?: string;
  trend?: "up" | "down" | "flat";
  trendLabel?: string;
  sparkData?: { v: number }[];
  className?: string;
}

/**
 * MetricCard — Reusable card for a single health metric.
 * Shows icon, label, big value, optional sparkline, and trend indicator.
 */
export function MetricCard({
  icon,
  label,
  value,
  unit,
  trend,
  trendLabel,
  sparkData,
  className,
}: MetricCardProps) {
  const { mode } = useTheme();
  const chartColor = mode === "day" ? "#C0846D" : "#4FD1C5";
  const trendColor = trend === "up"
    ? (mode === "day" ? "#7A9A6D" : "#68D391")
    : trend === "down"
      ? (mode === "day" ? "#C06D6D" : "#FC8181")
      : "var(--text-secondary)";

  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;

  return (
    <GlassCard className={className}>
      <div className="flex items-center gap-2 mb-1">
        <span style={{ color: "var(--accent-primary)" }}>{icon}</span>
        <LabelCaps>{label}</LabelCaps>
      </div>
      <div className="flex items-baseline gap-2 mt-2">
        <span className="font-display text-2xl" style={{
          fontFamily: "var(--font-display)",
          fontWeight: 400,
          color: "var(--text-primary)",
        }}>
          {value}
        </span>
        {unit && (
          <span className="text-sm text-[var(--text-secondary)]">{unit}</span>
        )}
      </div>
      {trend && trendLabel && (
        <div className="flex items-center gap-1 mt-1">
          <TrendIcon size={12} style={{ color: trendColor }} />
          <span className="text-xs" style={{ color: trendColor }}>{trendLabel}</span>
        </div>
      )}
      {sparkData && (
        <div className="h-12 mt-3">
          <ResponsiveContainer>
            <LineChart data={sparkData}>
              <Line type="monotone" dataKey="v" stroke={chartColor} strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </GlassCard>
  );
}
