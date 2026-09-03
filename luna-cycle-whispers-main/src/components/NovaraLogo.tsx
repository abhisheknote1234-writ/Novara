export function NovaraLogo({ className = "w-6 h-6", color = "currentColor" }: { className?: string; color?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      {/* Central leaf */}
      <path d="M12 3C12 3 15 7 15 12C15 17 12 21 12 21C12 21 9 17 9 12C9 7 12 3 12 3Z" fill="currentColor" fillOpacity="0.15" />
      <path d="M12 8V18" strokeWidth="1.2" />
      {/* Left leaf */}
      <path d="M11 14C8 13 5 15 4 18C7 19 10 18 11 14Z" fill="currentColor" fillOpacity="0.15" />
      {/* Right leaf */}
      <path d="M13 14C16 13 19 15 20 18C17 19 14 18 13 14Z" fill="currentColor" fillOpacity="0.15" />
    </svg>
  );
}
