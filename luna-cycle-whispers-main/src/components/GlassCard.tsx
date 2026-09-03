import { type ReactNode } from "react";
import { twMerge } from "tailwind-merge";

export function GlassCard({ children, className = "", hover = true, style }: { children: ReactNode; className?: string; hover?: boolean; style?: React.CSSProperties }) {
  return (
    <div
      className={twMerge("glass p-5 md:p-6", hover && "glass-hover", className)}
      style={{
        position: "relative",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function LabelCaps({ children }: { children: ReactNode }) {
  return <div className="label-caps">{children}</div>;
}
