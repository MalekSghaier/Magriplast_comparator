import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import FooterCredit from "../components/layout/FooterCredit";
import { Zap, BarChart3, ShieldCheck, AlertCircle, ArrowRight, Loader2, ScanText } from "lucide-react";

const C = {
  primary: "#1e3a5f",
  accent: "#3e1f6d",
  border: "#e0e7ef",
  text: "#37474f",
  muted: "#546e7a",
  errorBg: "#fdecea",
  errorBorder: "#ef9a9a",
  errorText: "#b71c1c",
};

function FloatingInput({ label, type = "text", value, onChange, placeholder, autoComplete }) {
  const [focused, setFocused] = useState(false);
  const active = focused || value;

  return (
    <div style={{ position: "relative", marginBottom: "22px" }}>
      <label style={{
        position: "absolute",
        left: "14px",
        top: active ? "-9px" : "14px",
        fontSize: active ? "0.70rem" : "0.875rem",
        fontWeight: active ? 700 : 400,
        color: focused ? C.primary : C.muted,
        background: "white",
        padding: "0 5px",
        transition: "all 0.18s cubic-bezier(.4,0,.2,1)",
        pointerEvents: "none",
        zIndex: 1,
        letterSpacing: active ? "0.04em" : "0",
        textTransform: active ? "uppercase" : "none",
      }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={onChange}
        autoComplete={autoComplete}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          width: "100%",
          padding: "14px 16px",
          border: `1.5px solid ${focused ? C.primary : C.border}`,
          borderRadius: "10px",
          fontSize: "0.875rem",
          color: C.text,
          outline: "none",
          boxSizing: "border-box",
          transition: "border-color 0.18s, box-shadow 0.18s",
          background: "white",
          boxShadow: focused ? `0 0 0 3px rgba(30,58,95,0.08)` : "none",
          fontFamily: "inherit",
        }}
      />
    </div>
  );
}

const FEATURES = [
  { icon: ScanText,    text: "Extraction automatique par OCR" },
  { icon: Zap,         text: "Comparaison intelligente des lignes" },
  { icon: BarChart3,   text: "Rapports d'audit détaillés" },
  { icon: ShieldCheck, text: "Données sécurisées et privées" },
];

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || "/";

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.response?.data?.detail || "Identifiants invalides");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh", position: "relative", fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display:ital@0;1&display=swap');
        *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

        @keyframes fadeUp    { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }
        @keyframes fadeIn    { from { opacity:0 } to { opacity:1 } }
        @keyframes float1    { 0%,100%{transform:translateY(0) rotate(0deg)} 50%{transform:translateY(-22px) rotate(3deg)} }
        @keyframes float2    { 0%,100%{transform:translateY(0) rotate(0deg)} 50%{transform:translateY(16px) rotate(-2deg)} }
        @keyframes float3    { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-12px)} }
        @keyframes spin      { to { transform: rotate(360deg); } }
        @keyframes shimmer   { 0%{background-position:200% 0} 100%{background-position:-200% 0} }

        .login-submit:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 12px 32px rgba(30,58,95,0.38), 0 2px 8px rgba(62,31,109,0.22);
        }
        .login-submit:active:not(:disabled) { transform: translateY(0); }

        .brand-divider { height: 1px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.15), transparent); margin: 40px 0; }

        @media (max-width: 820px) {
          .brand-panel { display: none !important; }
          .form-panel { padding-top: 48px !important; }
        }
      `}</style>

      {/* ── Brand panel ─────────────────────────────────────────────── */}
      <div className="brand-panel" style={{
        flex: "0 0 46%",
        background: `linear-gradient(155deg, #0f2240 0%, #1e3a5f 35%, #2a1854 70%, #3e1f6d 100%)`,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: "64px 56px",
        position: "relative",
        overflow: "hidden",
      }}>
        {/* Grain overlay */}
        <div style={{
          position: "absolute", inset: 0, zIndex: 0,
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E")`,
          backgroundRepeat: "repeat",
          backgroundSize: "200px",
          opacity: 0.6,
          pointerEvents: "none",
        }} />

        {/* Grid dot texture */}
        <div style={{
          position: "absolute", inset: 0, zIndex: 0,
          backgroundImage: "radial-gradient(rgba(255,255,255,0.055) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
          pointerEvents: "none",
        }} />

        {/* Orbs */}
        {[
          { w:420, h:420, top:"-130px", right:"-130px", op:0.07, anim:"float1 9s ease-in-out infinite", blur:80 },
          { w:280, h:280, bottom:"20px", left:"-90px", op:0.06, anim:"float2 12s ease-in-out infinite", blur:60 },
          { w:150, h:150, bottom:"260px", right:"50px", op:0.09, anim:"float3 7s ease-in-out infinite", blur:30 },
          { w:80,  h:80,  top:"150px", left:"70px", op:0.08, anim:"float1 8s ease-in-out infinite 1.5s", blur:20 },
        ].map((o, i) => (
          <div key={i} style={{
            position: "absolute",
            width: o.w, height: o.h,
            top: o.top, bottom: o.bottom, left: o.left, right: o.right,
            borderRadius: "50%",
            background: `radial-gradient(circle, rgba(255,255,255,${o.op + 0.03}), rgba(255,255,255,0))`,
            animation: o.anim,
            filter: `blur(${o.blur}px)`,
            pointerEvents: "none",
            zIndex: 0,
          }} />
        ))}

        {/* Frosted bottom strip */}
        <div style={{
          position: "absolute", bottom: 0, left: 0, right: 0, height: "120px",
          background: "linear-gradient(to top, rgba(15,34,64,0.6), transparent)",
          zIndex: 0, pointerEvents: "none",
        }} />

        <div style={{ position: "relative", zIndex: 1, animation: "fadeUp 0.7s ease both" }}>
          {/* Logo */}
          <div style={{ display: "flex", alignItems: "center", gap: "14px", marginBottom: "52px" }}>
            <img
              src="/logo.png"
              alt="Magriplast logo"
              style={{
                height: "44px",
                width: "auto",
                objectFit: "contain",
                display: "block",
                mixBlendMode: "screen",
              }}
            />
            <span style={{
              color: "white", fontSize: "1.2rem", fontWeight: 700,
              letterSpacing: "-0.3px",
              fontFamily: "'DM Sans', sans-serif",
            }}>
              Magriplast
            </span>
          </div>

          <h1 style={{
            color: "white",
            fontFamily: "'DM Serif Display', Georgia, serif",
            fontSize: "2.55rem",
            fontWeight: 400,
            lineHeight: 1.15,
            letterSpacing: "-0.5px",
            marginBottom: "18px",
          }}>
            Vérification<br/>
            <em style={{ fontStyle: "italic", color: "rgba(255,255,255,0.75)" }}>intelligente</em>
            <br/>de documents
          </h1>

          <p style={{
            color: "rgba(255,255,255,0.55)",
            fontSize: "0.92rem",
            lineHeight: 1.8,
            marginBottom: "44px",
            maxWidth: "320px",
            fontWeight: 400,
          }}>
            Comparez vos factures fournisseurs avec précision grâce à l'intelligence artificielle et l'OCR avancé.
          </p>

          <div className="brand-divider" />

          {FEATURES.map((f, i) => {
            const Icon = f.icon;
            return (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: "14px",
                marginBottom: "14px",
                animation: `fadeUp 0.5s ease ${0.1 * i + 0.4}s both`,
              }}>
                <div style={{
                  width: "34px", height: "34px", borderRadius: "9px",
                  background: "rgba(255,255,255,0.08)",
                  border: "1px solid rgba(255,255,255,0.13)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0,
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.1)",
                }}>
                  <Icon size={15} color="rgba(255,255,255,0.80)" strokeWidth={2} />
                </div>
                <span style={{ color: "rgba(255,255,255,0.78)", fontSize: "0.865rem", fontWeight: 500 }}>
                  {f.text}
                </span>
              </div>
            );
          })}
        </div>

        {/* Status badge */}
        <div style={{
          position: "absolute", bottom: "28px", left: "56px",
          display: "flex", alignItems: "center", gap: "8px",
          zIndex: 1, animation: "fadeIn 0.6s ease 0.9s both",
        }}>
          <div style={{
            width: "7px", height: "7px", borderRadius: "50%",
            background: "#4caf50",
            boxShadow: "0 0 0 3px rgba(76,175,80,0.25)",
          }} />
          <span style={{ color: "rgba(255,255,255,0.38)", fontSize: "0.73rem", letterSpacing: "0.03em" }}>
            Système opérationnel
          </span>
        </div>
      </div>

      {/* ── Form panel ───────────────────────────────────────────────── */}
      <div className="form-panel" style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#eef2f8",
        padding: "40px 24px 56px",
        backgroundImage: "radial-gradient(ellipse at 70% 20%, rgba(30,58,95,0.06) 0%, transparent 60%), radial-gradient(ellipse at 20% 80%, rgba(62,31,109,0.05) 0%, transparent 55%)",
      }}>
        <div style={{
          width: "100%",
          maxWidth: "440px",
          animation: "fadeUp 0.55s ease 0.2s both",
        }}>
          {/* Card */}
          <div style={{
            background: "white",
            borderRadius: "20px",
            padding: "48px 44px",
            boxShadow: "0 2px 4px rgba(0,0,0,0.04), 0 8px 24px rgba(30,58,95,0.08), 0 32px 64px rgba(30,58,95,0.07)",
            border: "1px solid rgba(255,255,255,0.9)",
          }}>
            <div style={{ marginBottom: "36px" }}>
              <h2 style={{
                color: C.primary,
                fontFamily: "'DM Serif Display', Georgia, serif",
                fontSize: "1.85rem",
                fontWeight: 400,
                letterSpacing: "-0.3px",
                marginBottom: "8px",
                lineHeight: 1.2,
              }}>
                Bon retour
              </h2>
              <p style={{ color: C.muted, fontSize: "0.875rem", lineHeight: 1.6 }}>
                Connectez-vous à votre espace de traitement
              </p>
            </div>

            {error && (
              <div style={{
                background: C.errorBg,
                border: `1px solid ${C.errorBorder}`,
                borderRadius: "10px",
                padding: "12px 16px",
                color: C.errorText,
                fontSize: "0.84rem",
                marginBottom: "24px",
                display: "flex",
                alignItems: "center",
                gap: "10px",
              }}>
                <AlertCircle size={15} color={C.errorText} strokeWidth={2.5} style={{ flexShrink: 0 }} />
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit}>
              <FloatingInput
                label="Adresse e-mail"
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoComplete="email"
              />
              <FloatingInput
                label="Mot de passe"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
              />

              <button
                type="submit"
                disabled={loading}
                className="login-submit"
                style={{
                  width: "100%",
                  padding: "15px",
                  background: loading
                    ? "#90a4ae"
                    : `linear-gradient(135deg, ${C.primary} 0%, #2a4a7f 40%, ${C.accent} 100%)`,
                  color: "white",
                  border: "none",
                  borderRadius: "10px",
                  fontSize: "0.9rem",
                  fontWeight: 700,
                  cursor: loading ? "not-allowed" : "pointer",
                  letterSpacing: "0.3px",
                  transition: "transform 0.18s, box-shadow 0.18s",
                  marginTop: "10px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "9px",
                  fontFamily: "inherit",
                  boxShadow: loading ? "none" : "0 4px 16px rgba(30,58,95,0.28), 0 1px 4px rgba(0,0,0,0.12)",
                }}
              >
                {loading ? (
                  <>
                    <Loader2 size={16} color="white" style={{ animation: "spin 0.7s linear infinite" }} />
                    Connexion…
                  </>
                ) : (
                  <>
                    Se connecter
                    <ArrowRight size={16} color="white" strokeWidth={2.5} />
                  </>
                )}
              </button>
            </form>
          </div>

          <p style={{ textAlign: "center", marginTop: "24px", color: C.muted, fontSize: "0.86rem" }}>
            Pas encore de compte ?{" "}
            <Link to="/register" style={{ color: C.primary, fontWeight: 700, textDecoration: "none" }}>
              Créer un compte
            </Link>
          </p>
        </div>
      </div>
      <FooterCredit fixed />
    </div>
  );
}
