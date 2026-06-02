import { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useSidebar } from "../../context/SidebarContext";
import { useAuth } from "../../context/AuthContext";
import { getRecentJobs } from "../../api/jobs";

const P = {
  bg:     "#1e3a5f",
  border: "rgba(255,255,255,0.08)",
  hover:  "rgba(255,255,255,0.065)",
  active: "rgba(255,255,255,0.11)",
  text:   "rgba(255,255,255,0.87)",
  muted:  "rgba(255,255,255,0.42)",
};

// ── Icons ──────────────────────────────────────────────
const Icon = ({ d, extra }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    {d}
    {extra}
  </svg>
);

const UploadIcon   = () => <Icon d={<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></>} />;
const JobsIcon     = () => <Icon d={<><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></>} />;
const AdminIcon    = () => <Icon d={<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>} />;
const CollapseIcon = ({ right }) => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    {right
      ? <polyline points="9 18 15 12 9 6"/>
      : <polyline points="15 18 9 12 15 6"/>}
  </svg>
);
const LogoutIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
    <polyline points="16 17 21 12 16 7"/>
    <line x1="21" y1="12" x2="9" y2="12"/>
  </svg>
);

// ── NavItem ─────────────────────────────────────────────
function NavItem({ to, icon, label, col, onClick }) {
  const loc = useLocation();
  const active = to === "/" ? loc.pathname === "/" : loc.pathname.startsWith(to);
  const [hov, setHov] = useState(false);

  return (
    <Link to={to} onClick={onClick} title={col ? label : undefined} style={{ textDecoration: "none" }}>
      <div
        onMouseEnter={() => setHov(true)}
        onMouseLeave={() => setHov(false)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: col ? 0 : "11px",
          justifyContent: col ? "center" : "flex-start",
          padding: col ? "11px" : "9px 13px",
          margin: "1px 8px",
          borderRadius: "9px",
          background: active ? P.active : hov ? P.hover : "transparent",
          borderLeft: active ? "3px solid rgba(255,255,255,0.62)" : "3px solid transparent",
          cursor: "pointer",
          transition: "background 0.14s",
        }}
      >
        <span style={{ color: active ? "white" : P.text, display: "flex" }}>{icon}</span>
        {!col && (
          <span style={{
            color: active ? "white" : P.text,
            fontSize: "0.878rem",
            fontWeight: active ? 700 : 500,
          }}>
            {label}
          </span>
        )}
      </div>
    </Link>
  );
}

// ── Section label ────────────────────────────────────────
function SectionLabel({ label, col }) {
  if (col) return <div style={{ height: "1px", background: P.border, margin: "8px 12px" }} />;
  return (
    <p style={{
      color: P.muted, fontSize: "0.67rem", fontWeight: 700,
      letterSpacing: "0.85px", textTransform: "uppercase",
      padding: "10px 20px 5px",
    }}>{label}</p>
  );
}

// ── Status dot ───────────────────────────────────────────
function Dot({ status }) {
  const c = { completed: "#4caf50", failed: "#f44336", processing: "#2196f3" };
  return (
    <div style={{
      width: "6px", height: "6px", borderRadius: "50%", flexShrink: 0,
      background: c[status?.toLowerCase()] || "#ff9800",
    }} />
  );
}

// ── Sidebar ──────────────────────────────────────────────
export default function Sidebar({ mobile = false }) {
  const { collapsed, toggleCollapse, closeMobile } = useSidebar();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [recentJobs, setRecentJobs] = useState([]);

  useEffect(() => {
    getRecentJobs(6).then(setRecentJobs).catch(() => {});
  }, []);

  const col = mobile ? false : collapsed;
  const close = mobile ? closeMobile : undefined;

  const initials = user?.full_name
    ? user.full_name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2)
    : "?";

  const handleLogout = () => {
    logout();
    if (mobile) closeMobile();
    navigate("/login");
  };

  return (
    <div style={{
      width: "100%", height: "100%",
      display: "flex", flexDirection: "column",
      background: P.bg, overflow: "hidden",
      fontFamily: "'Inter', system-ui, sans-serif",
    }}>

      {/* ── Logo / Header ─────────────────────────────── */}
      <div style={{
        padding: col ? "16px 0" : "16px",
        borderBottom: `1px solid ${P.border}`,
        display: "flex", alignItems: "center",
        justifyContent: col ? "center" : "space-between",
        flexShrink: 0, minHeight: "64px", gap: "10px",
      }}>
        <Link to="/" onClick={close} style={{
          display: "flex", alignItems: "center", gap: "10px", textDecoration: "none",
        }}>
          {/* Bare logo — no container, no border, blends against dark sidebar */}
          <img
            src="/logo.png"
            alt="Magriplast logo"
            style={{
              height: col ? "14px" : "20px",
              width: "auto",
              objectFit: "contain",
              display: "block",
              flexShrink: 0,
              mixBlendMode: "screen",
            }}
          />
          {!col && (
            <div>
              <p style={{ color: "white", fontSize: "0.95rem", fontWeight: 800, letterSpacing: "-0.3px", lineHeight: 1 }}>
                Magriplast
              </p>
              <p style={{ color: P.muted, fontSize: "0.67rem", marginTop: "3px" }}>Document AI</p>
            </div>
          )}
        </Link>

        {/* Desktop collapse button (expanded state) */}
        {!col && !mobile && (
          <button onClick={toggleCollapse} style={{
            background: "rgba(255,255,255,0.06)",
            border: "1px solid rgba(255,255,255,0.10)",
            borderRadius: "7px", width: "28px", height: "28px",
            cursor: "pointer", color: P.muted, flexShrink: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            transition: "background 0.14s",
          }}
          onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.12)"}
          onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.06)"}
          >
            <CollapseIcon />
          </button>
        )}
      </div>

      {/* ── Nav items ─────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", padding: "10px 0" }}>

        <SectionLabel label="Principal" col={col} />
        <NavItem to="/"     icon={<UploadIcon />} label="Nouveau Document" col={col} onClick={close} />
        <NavItem to="/jobs" icon={<JobsIcon />}   label="Mes Travaux"      col={col} onClick={close} />

        {user?.is_superuser && (
          <>
            <SectionLabel label="Admin" col={col} />
            <NavItem to="/admin" icon={<AdminIcon />} label="Administration" col={col} onClick={close} />
          </>
        )}

        {/* Recent jobs (expanded only) */}
        {!col && recentJobs.length > 0 && (
          <>
            <div style={{ height: "1px", background: P.border, margin: "10px 14px" }} />
            <p style={{
              color: P.muted, fontSize: "0.67rem", fontWeight: 700,
              letterSpacing: "0.85px", textTransform: "uppercase",
              padding: "4px 20px 5px",
            }}>Récents</p>

            {recentJobs.slice(0, 6).map(job => (
              <Link key={job.id} to={`/jobs/${job.id}`} onClick={close} style={{ textDecoration: "none" }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: "9px",
                  padding: "7px 14px", margin: "1px 8px", borderRadius: "8px", cursor: "pointer",
                  transition: "background 0.13s",
                }}
                onMouseEnter={e => e.currentTarget.style.background = P.hover}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  <Dot status={job.status} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{
                      color: P.text, fontSize: "0.79rem", fontWeight: 500,
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}>
                      {job.filename || `Job #${job.id}`}
                    </p>
                    <p style={{ color: P.muted, fontSize: "0.69rem" }}>{job.status}</p>
                  </div>
                </div>
              </Link>
            ))}
          </>
        )}

        {/* Collapse toggle when sidebar is collapsed (desktop) */}
        {col && !mobile && (
          <>
            <div style={{ height: "1px", background: P.border, margin: "8px 12px" }} />
            <div style={{ display: "flex", justifyContent: "center", padding: "4px 0" }}>
              <button onClick={toggleCollapse} title="Développer" style={{
                background: "rgba(255,255,255,0.06)",
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: "7px", width: "36px", height: "28px",
                cursor: "pointer", color: P.muted,
                display: "flex", alignItems: "center", justifyContent: "center",
                transition: "background 0.14s",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.12)"}
              onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.06)"}
              >
                <CollapseIcon right />
              </button>
            </div>
          </>
        )}
      </div>

      {/* ── User section ──────────────────────────────── */}
      <div style={{
        borderTop: `1px solid ${P.border}`,
        padding: col ? "12px 0" : "12px",
        flexShrink: 0,
      }}>
        {!col ? (
          <div style={{
            display: "flex", alignItems: "center", gap: "10px",
            padding: "8px 10px", borderRadius: "10px",
            background: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}>
            <div style={{
              width: "34px", height: "34px", borderRadius: "8px", flexShrink: 0,
              background: "rgba(255,255,255,0.13)",
              border: "1px solid rgba(255,255,255,0.16)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "white", fontSize: "0.77rem", fontWeight: 800,
            }}>
              {initials}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{
                color: "white", fontSize: "0.82rem", fontWeight: 700,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {user?.full_name}
              </p>
              <p style={{
                color: P.muted, fontSize: "0.70rem",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {user?.email}
              </p>
            </div>
            <button onClick={handleLogout} title="Se déconnecter" style={{
              background: "none", border: "none", cursor: "pointer",
              color: P.muted, padding: "5px", borderRadius: "6px",
              display: "flex", alignItems: "center",
              transition: "color 0.13s, background 0.13s",
            }}
            onMouseEnter={e => { e.currentTarget.style.color = "#ef5350"; e.currentTarget.style.background = "rgba(239,83,80,0.12)"; }}
            onMouseLeave={e => { e.currentTarget.style.color = P.muted;   e.currentTarget.style.background = "none"; }}
            >
              <LogoutIcon />
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "8px" }}>
            <div style={{
              width: "36px", height: "36px", borderRadius: "8px",
              background: "rgba(255,255,255,0.10)",
              border: "1px solid rgba(255,255,255,0.14)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "white", fontSize: "0.77rem", fontWeight: 800,
            }}>
              {initials}
            </div>
            <button onClick={handleLogout} title="Se déconnecter" style={{
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: "7px", width: "36px", height: "28px",
              cursor: "pointer", color: P.muted,
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "color 0.15s, background 0.15s",
            }}
            onMouseEnter={e => { e.currentTarget.style.color = "#ef5350"; e.currentTarget.style.background = "rgba(239,83,80,0.12)"; }}
            onMouseLeave={e => { e.currentTarget.style.color = P.muted;   e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
            >
              <LogoutIcon />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}