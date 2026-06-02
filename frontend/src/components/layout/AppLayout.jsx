import { useSidebar } from "../../context/SidebarContext";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import FooterCredit from "./FooterCredit";

const W  = 256; // expanded
const CW = 68;  // collapsed

export default function AppLayout({ children }) {
  const { collapsed, mobileOpen, closeMobile } = useSidebar();

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', system-ui, sans-serif; }
        @media (max-width: 1023px) {
          .desktop-sidebar  { display: none !important; }
          .sidebar-margin   { margin-left: 0 !important; transition: none !important; }
        }
        @media (min-width: 1024px) {
          .mobile-drawer    { display: none !important; }
          .mobile-overlay   { display: none !important; }
        }
        ::-webkit-scrollbar       { width: 6px; }
        ::-webkit-scrollbar-track { background: #f0f4ff; }
        ::-webkit-scrollbar-thumb { background: #90a4be; border-radius: 3px; }
      `}</style>

      {/* ── Desktop sidebar (fixed) ──────────────────── */}
      <div className="desktop-sidebar" style={{
        position: "fixed",
        top: 0, left: 0, bottom: 0,
        width: collapsed ? CW : W,
        transition: "width 0.22s ease",
        zIndex: 50,
      }}>
        <Sidebar />
      </div>

      {/* ── Mobile backdrop ──────────────────────────── */}
      {mobileOpen && (
        <div
          className="mobile-overlay"
          onClick={closeMobile}
          style={{
            position: "fixed", inset: 0,
            background: "rgba(15,28,46,0.58)",
            backdropFilter: "blur(2px)",
            zIndex: 198,
            cursor: "pointer",
          }}
        />
      )}

      {/* ── Mobile drawer ────────────────────────────── */}
      <div className="mobile-drawer" style={{
        position: "fixed",
        top: 0, left: 0, bottom: 0,
        width: 272,
        zIndex: 199,
        transform: mobileOpen ? "translateX(0)" : "translateX(-100%)",
        transition: "transform 0.22s ease",
        boxShadow: mobileOpen ? "4px 0 32px rgba(15,28,46,0.25)" : "none",
      }}>
        <Sidebar mobile />
      </div>

      {/* ── Main content ─────────────────────────────── */}
      <div
        className="sidebar-margin"
        style={{
          marginLeft: collapsed ? CW : W,
          transition: "margin-left 0.22s ease",
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <TopBar />
        <main style={{ flex: 1, background: "#f4f7fb" }}>
          {children}
        </main>
        <FooterCredit />
      </div>
    </>
  );
}
