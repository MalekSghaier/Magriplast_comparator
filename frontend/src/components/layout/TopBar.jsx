import { useLocation, Link } from "react-router-dom";
import { useSidebar } from "../../context/SidebarContext";

const TITLES = {
  "/":       { label: "Nouveau Document", sub: "Téléversez vos documents" },
  "/jobs":   { label: "Mes Travaux",      sub: "Historique de traitement" },
  "/admin":  { label: "Administration",   sub: "Gestion du système" },
};

function getTitle(pathname) {
  if (TITLES[pathname]) return TITLES[pathname];
  if (pathname.startsWith("/jobs/"))    return { label: "Suivi du traitement", sub: "Statut en temps réel" };
  if (pathname.startsWith("/results/")) return { label: "Résultats",           sub: "Analyse complète" };
  if (pathname.startsWith("/review/"))  return { label: "Révision",            sub: "Validation manuelle" };
  return { label: "Magriplast", sub: "" };
}

export default function TopBar() {
  const { toggleMobile } = useSidebar();
  const loc = useLocation();
  const { label, sub } = getTitle(loc.pathname);

  return (
    <>
      <style>{`
        @media (min-width: 1024px) { .mob-only { display:none !important; } }
        @media (max-width: 1023px) { .desk-only { display:none !important; } }
      `}</style>

      <div style={{
        height: "58px",
        background: "white",
        borderBottom: "1px solid #e0e7ef",
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        gap: "14px",
        flexShrink: 0,
        position: "sticky",
        top: 0,
        zIndex: 40,
        boxShadow: "0 1px 6px rgba(30,58,95,0.05)",
      }}>

        {/* Hamburger — mobile only */}
        <button
          className="mob-only"
          onClick={toggleMobile}
          style={{
            background: "none", border: "none", cursor: "pointer",
            padding: "7px", borderRadius: "8px", color: "#546e7a",
            display: "flex", alignItems: "center",
            transition: "background 0.13s",
          }}
          onMouseEnter={e => e.currentTarget.style.background = "#f4f7fb"}
          onMouseLeave={e => e.currentTarget.style.background = "none"}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <line x1="3" y1="6"  x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>

        {/* Logo (visible on desktop and mobile) */}
        <Link to="/" style={{
          display: "flex", alignItems: "center", gap: "10px", textDecoration: "none",
        }}>
          {/* Bare image only (no container), larger on desktop */}
          <img
            src="/logo.png"
            alt="Magriplast logo"
            style={{
              height: "38px",
              width: "auto",
              objectFit: "contain",
              display: "block",
            }}
          />
        
        </Link>

        {/* Desktop page title */}
        <div className="desk-only">
          <p style={{ color: "#1e3a5f", fontSize: "0.92rem", fontWeight: 700, lineHeight: 1.2 }}>
            {label}
          </p>
          {sub && (
            <p style={{ color: "#546e7a", fontSize: "0.72rem", marginTop: "1px" }}>{sub}</p>
          )}
        </div>

        <div style={{ flex: 1 }} />

        {/* Quick action button — desktop only */}
        <Link to="/" className="desk-only" style={{ textDecoration: "none" }}>
          <button style={{
            display: "flex", alignItems: "center", gap: "7px",
            padding: "7px 14px",
            background: "linear-gradient(135deg,#1e3a5f,#3e1f6d)",
            color: "white", border: "none", borderRadius: "8px",
            fontSize: "0.80rem", fontWeight: 700,
            cursor: "pointer", letterSpacing: "0.1px",
            transition: "opacity 0.15s, transform 0.15s",
            boxShadow: "0 2px 10px rgba(30,58,95,0.22)",
          }}
          onMouseEnter={e => { e.currentTarget.style.opacity="0.88"; e.currentTarget.style.transform="translateY(-1px)"; }}
          onMouseLeave={e => { e.currentTarget.style.opacity="1";    e.currentTarget.style.transform="none"; }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="12" y1="5" x2="12" y2="19"/>
              <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            Nouveau
          </button>
        </Link>
      </div>
    </>
  );
}