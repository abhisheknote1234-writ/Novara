import { useState } from "react";
import { useTheme } from "@/context/ThemeContext";
import { Link, useLocation } from "@tanstack/react-router";
import { Sun, Moon, Menu, X, Moon as MoonIcon, Heart, Activity, Brain, TrendingUp, Settings, BarChart3 } from "lucide-react";
import { NovaraLogo } from "@/components/NovaraLogo";

/* Landing page nav links (scroll anchors) */
const landingLinks = [
  { label: "Technology", href: "#technology" },
  { label: "Design", href: "#design" },
  { label: "Features", href: "#features" },
  { label: "Roadmap", href: "#roadmap" },
];

/* App nav links (routes) */
const appLinks = [
  { label: "Sleep", to: "/sleep", icon: MoonIcon },
  { label: "Heart", to: "/heart", icon: Heart },
  { label: "Recovery", to: "/recovery", icon: Activity },
  { label: "Activity", to: "/activity", icon: TrendingUp },
  { label: "Insights", to: "/insights", icon: BarChart3 },
  { label: "AI", to: "/assistant", icon: Brain },
  { label: "Settings", to: "/settings", icon: Settings },
];

export function Sidebar() {
  const { mode, toggle } = useTheme();
  const location = useLocation();
  const isLanding = location.pathname === "/";

  const scrollTo = (href: string) => {
    const el = document.querySelector(href);
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <nav className="top-nav">
      {/* Logo */}
      <Link
        to="/"
        className="flex items-center gap-2.5 group"
      >
        <div
          className="w-8 h-8 rounded-full border flex items-center justify-center transition-transform group-hover:scale-105"
          style={{ borderColor: "var(--accent-primary)", color: "var(--accent-primary)", background: "var(--glass-bg)" }}
        >
          <NovaraLogo className="w-5 h-5" />
        </div>
        <span
          className="font-display text-xl tracking-wide font-normal"
          style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
        >
          novara
        </span>
      </Link>

      {/* Desktop nav links */}
      <div className="hidden md:flex items-center gap-1">
        {isLanding ? (
          /* Landing page: section anchors + app link */
          <>
            {landingLinks.map((link) => (
              <button
                key={link.href}
                onClick={() => scrollTo(link.href)}
                className="text-sm px-3 py-1.5 rounded-lg transition-colors"
                style={{ color: "var(--text-secondary)" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text-primary)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-secondary)")}
              >
                {link.label}
              </button>
            ))}
            <Link
              to="/sleep"
              className="btn-primary flex items-center gap-2 text-sm ml-3 px-5 py-2"
            >
              Launch App
            </Link>
          </>
        ) : (
          /* App pages: route navigation */
          <>
            {appLinks.map((link) => {
              const isActive = location.pathname === link.to;
              const Icon = link.icon;
              return (
                <Link
                  key={link.to}
                  to={link.to}
                  className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg transition-all"
                  style={{
                    color: isActive ? "var(--nav-active-color)" : "var(--text-secondary)",
                    background: isActive ? "var(--nav-active-bg)" : "transparent",
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.color = "var(--text-primary)";
                      e.currentTarget.style.background = "var(--nav-active-bg)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) {
                      e.currentTarget.style.color = "var(--text-secondary)";
                      e.currentTarget.style.background = "transparent";
                    }
                  }}
                >
                  <Icon size={14} strokeWidth={1.5} />
                  {link.label}
                </Link>
              );
            })}
          </>
        )}

        {/* Theme toggle */}
        <button className="theme-toggle ml-3" onClick={toggle} aria-label="Toggle day/night mode">
          <div className="toggle-knob">
            <span style={{ fontSize: 10 }}>{mode === "day" ? "☀" : "☾"}</span>
          </div>
        </button>
      </div>

      {/* Mobile: theme toggle only (hamburger handled by MobileNav) */}
      <div className="md:hidden flex items-center gap-3">
        <button
          onClick={toggle}
          className="w-9 h-9 rounded-lg flex items-center justify-center border"
          style={{ borderColor: "var(--border-subtle)", color: "var(--text-secondary)" }}
          aria-label="Toggle theme"
        >
          {mode === "day" ? <Sun size={16} strokeWidth={1.5} /> : <Moon size={16} strokeWidth={1.5} />}
        </button>
      </div>
    </nav>
  );
}

export function MobileNav() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const isLanding = location.pathname === "/";

  const scrollTo = (href: string) => {
    const el = document.querySelector(href);
    if (el) el.scrollIntoView({ behavior: "smooth" });
    setOpen(false);
  };

  return (
    <>
      {/* Hamburger button — fixed top-right on mobile */}
      <button
        className="md:hidden fixed top-4 right-16 z-50 w-9 h-9 rounded-lg flex items-center justify-center border"
        style={{
          borderColor: "var(--border-subtle)",
          color: "var(--text-secondary)",
          background: "var(--glass-bg)",
          backdropFilter: "blur(12px)",
        }}
        onClick={() => setOpen(!open)}
        aria-label="Toggle menu"
      >
        {open ? <X size={16} strokeWidth={1.5} /> : <Menu size={16} strokeWidth={1.5} />}
      </button>

      {/* Mobile slide-down menu */}
      {open && (
        <div
          className="md:hidden fixed inset-0 z-40 pt-20 px-6 pb-8 flex flex-col gap-2"
          style={{
            background: "var(--sidebar-bg)",
            backdropFilter: "blur(24px) saturate(1.1)",
          }}
        >
          {isLanding ? (
            <>
              {landingLinks.map((link) => (
                <button
                  key={link.href}
                  onClick={() => scrollTo(link.href)}
                  className="text-left py-4 border-b text-lg"
                  style={{
                    borderColor: "var(--border-subtle)",
                    color: "var(--text-primary)",
                    fontFamily: "var(--font-display)",
                  }}
                >
                  {link.label}
                </button>
              ))}
              <Link
                to="/sleep"
                className="btn-primary text-center mt-4 py-3 text-lg"
                onClick={() => setOpen(false)}
              >
                Launch App
              </Link>
            </>
          ) : (
            appLinks.map((link) => {
              const isActive = location.pathname === link.to;
              const Icon = link.icon;
              return (
                <Link
                  key={link.to}
                  to={link.to}
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-3 text-left py-4 border-b text-lg"
                  style={{
                    borderColor: "var(--border-subtle)",
                    color: isActive ? "var(--nav-active-color)" : "var(--text-primary)",
                    fontFamily: "var(--font-display)",
                  }}
                >
                  <Icon size={18} strokeWidth={1.5} />
                  {link.label}
                </Link>
              );
            })
          )}
        </div>
      )}
    </>
  );
}
