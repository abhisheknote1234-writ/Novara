import { Sidebar, MobileNav } from "./Sidebar";
import { DreamyAtmosphere } from "./StarField";

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen relative">
      <div className="cosmic-bg" />
      <DreamyAtmosphere />
      <Sidebar />
      <MobileNav />
      <main className="pt-24 md:pt-28 pb-16 px-4 md:px-10 max-w-[1280px] mx-auto relative" style={{ zIndex: 2 }}>
        {children}
      </main>
    </div>
  );
}
