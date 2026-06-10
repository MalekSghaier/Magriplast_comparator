import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ScanText, Upload, Cpu, CheckCircle2, AlertCircle, ArrowRight, Loader2 } from "lucide-react";

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

function FloatingInput({ label, type = "text", value, onChange, autoComplete, hint }) {
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
      {hint && <p style={{ color: C.muted, fontSize: "0.74rem", marginTop: "5px", paddingLeft: "4px" }}>{hint}</p>}
    </div>
  );
}

function StrengthBar({ password }) {
  const score = password.length === 0 ? 0
    : password.length < 6 ? 1
    : password.length < 8 ? 2
    : /[A-Z]/.test(password) && /[0-9]/.test(password) ? 4 : 3;

  const colors = ["transparent", "#f44336", "#ff9800", "#2196f3", "#4caf50"];
  const labels = ["", "Très faible", "Faible", "Moyen", "Fort"];

  if (!password) return null;

  return (
    <div style={{ marginBottom: "20px", marginTop: "-14px" }}>
      <div style={{ display: "flex", gap: "4px", marginBottom: "5px" }}>
        {[1, 2, 3, 4].map(i => (
          <div key={i} style={{
            flex: 1, height: "3px", borderRadius: "3px",
            background: i <= score ? colors[score] : "#e0e7ef",
            transition: "background 0.25s ease",
          }} />
        ))}
      </div>
      <p style={{ color: colors[score], fontSize: "0.73rem", fontWeight: 600 }}>{labels[score]}</p>
    </div>
  );
}

const STEPS = [
  { num: "01", icon: Upload,     title: "Téléversez vos documents", desc: "PDF de bon de commande et facture" },
  { num: "02", icon: Cpu,        title: "Analyse automatique",       desc: "OCR + IA extraient chaque ligne" },
  { num: "03", icon: CheckCircle2, title: "Résultat instantané",     desc: "Écarts détectés et rapport généré" },
];

export default function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (password !== confirm) { setError("Les mots de passe ne correspondent pas"); return; }
    if (password.length < 8)  { setError("Le mot de passe doit contenir au moins 8 caractères"); return; }

    setLoading(true);
    try {
      await register(email, fullName, password);
      navigate("/login", { replace: true, state: { registered: true, email } });
    } catch (err) {
      setError(err.response?.data?.detail || "Erreur lors de la création du compte");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display:ital@0;1&display=swap');
        *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
        @keyframes fadeUp  { from{opacity:0;transform:translateY(20px)} to{opacity:1;transform:translateY(0)} }
        @keyframes fadeIn  { from{opacity:0} to{opacity:1} }
        @keyframes float1  { 0%,100%{transform:translateY(0) rotate(0deg)} 50%{transform:translateY(-22px) rotate(3deg)} }
        @keyframes float2  { 0%,100%{transform:translateY(0)} 50%{transform:translateY(16px)} }
        @keyframes spin    { to{transform:rotate(360deg)} }

        .reg-submit:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 12px 32px rgba(62,31,109,0.38), 0 2px 8px rgba(30,58,95,0.22);
        }
        .reg-submit:active:not(:disabled) { transform:translateY(0); }

        @media(max-width:820px) {
          .brand-panel { display:none !important; }
          .form-panel  { padding: 36px 20px !important; }
        }
      `}</style>

      {/* ── Brand panel ──────────────────────────────────────────────── */}
      <div className="brand-panel" style={{
        flex: "0 0 40%",
        background: `linear-gradient(155deg, #2a1854 0%, #3e1f6d 35%, #1e3a5f 75%, #0f2240 100%)`,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: "64px 52px",
        position: "relative",
        overflow: "hidden",
      }}>
        {/* Grain */}
        <div style={{
          position: "absolute", inset: 0, zIndex: 0,
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E")`,
          backgroundRepeat: "repeat", backgroundSize: "200px", opacity: 0.6, pointerEvents: "none",
        }} />
        <div style={{
          position: "absolute", inset: 0, zIndex: 0,
          backgroundImage: "radial-gradient(rgba(255,255,255,0.055) 1px, transparent 1px)",
          backgroundSize: "28px 28px", pointerEvents: "none",
        }} />

        {/* Orbs */}
        {[
          { w:340, h:340, top:"-90px", right:"-90px", op:0.07, a:"float1 10s ease-in-out infinite", blur:70 },
          { w:240, h:240, bottom:"50px", left:"-70px", op:0.06, a:"float2 13s ease-in-out infinite", blur:55 },
          { w:110, h:110, top:"200px", right:"90px", op:0.09, a:"float1 8s ease-in-out infinite 0.5s", blur:25 },
        ].map((o, i) => (
          <div key={i} style={{
            position:"absolute", width:o.w, height:o.h,
            top:o.top, bottom:o.bottom, left:o.left, right:o.right,
            borderRadius:"50%",
            background:`radial-gradient(circle, rgba(255,255,255,${o.op + 0.03}), rgba(255,255,255,0))`,
            animation:o.a, filter:`blur(${o.blur}px)`,
            pointerEvents:"none", zIndex:0,
          }} />
        ))}

        <div style={{ position:"relative", zIndex:1 }}>
          {/* Logo */}
          <div style={{ display:"flex", alignItems:"center", gap:"13px", marginBottom:"48px" }}>
            <div style={{
              width:"48px", height:"48px", borderRadius:"14px",
              background:"rgba(255,255,255,0.10)",
              border:"1px solid rgba(255,255,255,0.20)",
              display:"flex", alignItems:"center", justifyContent:"center",
              backdropFilter:"blur(12px)",
              boxShadow:"0 4px 20px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.15)",
            }}>
              <ScanText size={22} color="white" strokeWidth={1.75} />
            </div>
            <span style={{
              color:"white", fontSize:"1.2rem", fontWeight:700,
              letterSpacing:"-0.3px", fontFamily:"'DM Sans', sans-serif",
            }}>Magriplast</span>
          </div>

          <h1 style={{
            color: "white",
            fontFamily: "'DM Serif Display', Georgia, serif",
            fontSize: "2.35rem",
            fontWeight: 400,
            lineHeight: 1.18,
            letterSpacing: "-0.5px",
            marginBottom: "16px",
          }}>
            Créez votre<br/>
            <em style={{ fontStyle:"italic", color:"rgba(255,255,255,0.72)" }}>espace de travail</em>
          </h1>

          <p style={{
            color:"rgba(255,255,255,0.55)", fontSize:"0.92rem",
            lineHeight:1.8, marginBottom:"44px", fontWeight:400,
          }}>
            Rejoignez Magriplast pour automatiser la vérification de vos documents fournisseurs.
          </p>

          {/* Separator */}
          <div style={{ height:"1px", background:"linear-gradient(90deg, transparent, rgba(255,255,255,0.14), transparent)", marginBottom:"36px" }} />

          {/* Steps */}
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            return (
              <div key={i} style={{
                display:"flex", gap:"16px", marginBottom:"24px",
                animation:`fadeUp 0.5s ease ${0.2 + i * 0.1}s both`,
              }}>
                <div style={{
                  width:"36px", height:"36px", borderRadius:"10px", flexShrink:0,
                  background:"rgba(255,255,255,0.09)",
                  border:"1px solid rgba(255,255,255,0.15)",
                  display:"flex", alignItems:"center", justifyContent:"center",
                  boxShadow:"inset 0 1px 0 rgba(255,255,255,0.1)",
                }}>
                  <Icon size={16} color="rgba(255,255,255,0.78)" strokeWidth={2} />
                </div>
                <div>
                  <p style={{ color:"rgba(255,255,255,0.88)", fontSize:"0.875rem", fontWeight:600, marginBottom:"2px" }}>
                    {s.title}
                  </p>
                  <p style={{ color:"rgba(255,255,255,0.45)", fontSize:"0.80rem", lineHeight:1.5 }}>{s.desc}</p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Status */}
        <div style={{
          position:"absolute", bottom:"28px", left:"52px",
          display:"flex", alignItems:"center", gap:"8px",
          zIndex:1, animation:"fadeIn 0.6s ease 0.9s both",
        }}>
          <div style={{
            width:"7px", height:"7px", borderRadius:"50%",
            background:"#4caf50",
            boxShadow:"0 0 0 3px rgba(76,175,80,0.25)",
          }} />
          <span style={{ color:"rgba(255,255,255,0.38)", fontSize:"0.73rem", letterSpacing:"0.03em" }}>
            Système opérationnel
          </span>
        </div>
      </div>

      {/* ── Form panel ───────────────────────────────────────────────── */}
      <div className="form-panel" style={{
        flex:1, display:"flex", alignItems:"center", justifyContent:"center",
        background:"#eef2f8", padding:"40px 24px", overflowY:"auto",
        backgroundImage:"radial-gradient(ellipse at 30% 20%, rgba(62,31,109,0.06) 0%, transparent 55%), radial-gradient(ellipse at 80% 80%, rgba(30,58,95,0.05) 0%, transparent 55%)",
      }}>
        <div style={{ width:"100%", maxWidth:"460px", animation:"fadeUp 0.55s ease 0.2s both" }}>
          <div style={{
            background:"white", borderRadius:"20px", padding:"48px 44px",
            boxShadow:"0 2px 4px rgba(0,0,0,0.04), 0 8px 24px rgba(30,58,95,0.08), 0 32px 64px rgba(30,58,95,0.07)",
            border:"1px solid rgba(255,255,255,0.9)",
          }}>
            <div style={{ marginBottom:"36px" }}>
              <h2 style={{
                color:C.primary,
                fontFamily:"'DM Serif Display', Georgia, serif",
                fontSize:"1.85rem", fontWeight:400,
                letterSpacing:"-0.3px", marginBottom:"8px", lineHeight:1.2,
              }}>
                Créer un compte
              </h2>
              <p style={{ color:C.muted, fontSize:"0.875rem", lineHeight:1.6 }}>
                Quelques secondes pour démarrer
              </p>
            </div>

            {error && (
              <div style={{
                background:C.errorBg, border:`1px solid ${C.errorBorder}`,
                borderRadius:"10px", padding:"12px 16px",
                color:C.errorText, fontSize:"0.84rem", marginBottom:"24px",
                display:"flex", alignItems:"center", gap:"10px",
              }}>
                <AlertCircle size={15} color={C.errorText} strokeWidth={2.5} style={{ flexShrink:0 }} />
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit}>
              <FloatingInput
                label="Nom complet"
                value={fullName}
                onChange={e => setFullName(e.target.value)}
                autoComplete="name"
              />
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
                autoComplete="new-password"
              />
              <StrengthBar password={password} />
              <FloatingInput
                label="Confirmer le mot de passe"
                type="password"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                autoComplete="new-password"
              />

              <button
                type="submit"
                disabled={loading}
                className="reg-submit"
                style={{
                  width:"100%", padding:"15px",
                  background: loading ? "#90a4ae" : `linear-gradient(135deg, ${C.accent} 0%, #2a1e7f 45%, ${C.primary} 100%)`,
                  color:"white", border:"none", borderRadius:"10px",
                  fontSize:"0.9rem", fontWeight:700,
                  cursor: loading ? "not-allowed" : "pointer",
                  letterSpacing:"0.3px",
                  transition:"transform 0.18s, box-shadow 0.18s",
                  marginTop:"6px",
                  display:"flex", alignItems:"center", justifyContent:"center", gap:"9px",
                  fontFamily:"inherit",
                  boxShadow: loading ? "none" : "0 4px 16px rgba(62,31,109,0.30), 0 1px 4px rgba(0,0,0,0.12)",
                }}
              >
                {loading ? (
                  <>
                    <Loader2 size={16} color="white" style={{ animation:"spin 0.7s linear infinite" }} />
                    Création…
                  </>
                ) : (
                  <>
                    Créer mon compte
                    <ArrowRight size={16} color="white" strokeWidth={2.5} />
                  </>
                )}
              </button>
            </form>
          </div>

          <p style={{ textAlign:"center", marginTop:"24px", color:C.muted, fontSize:"0.86rem" }}>
            Déjà un compte ?{" "}
            <Link to="/login" style={{ color:C.primary, fontWeight:700, textDecoration:"none" }}>
              Se connecter
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
