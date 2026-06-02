import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { ScanText } from "lucide-react";

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(155deg, #f4f7fb 0%, #eef2f8 100%)",
        fontFamily: "'DM Sans', system-ui, sans-serif",
      }}>
        <style>{`
          @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');
          @keyframes spin    { to { transform: rotate(360deg); } }
          @keyframes fadeIn  { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
          @keyframes pulse   { 0%,100% { opacity: 0.5; transform: scale(1); } 50% { opacity: 1; transform: scale(1.04); } }
        `}</style>

        <div style={{ textAlign: "center", animation: "fadeIn 0.4s ease both" }}>
          {/* Logo mark */}
          <div style={{
            width: "56px", height: "56px", borderRadius: "16px",
            background: "linear-gradient(135deg, #1e3a5f 0%, #3e1f6d 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            margin: "0 auto 20px",
            boxShadow: "0 8px 24px rgba(30,58,95,0.22), 0 2px 6px rgba(0,0,0,0.08)",
            animation: "pulse 2s ease-in-out infinite",
          }}>
            <ScanText size={26} color="white" strokeWidth={1.75} />
          </div>

          {/* Spinner ring */}
          <div style={{
            width: "36px", height: "36px",
            border: "2.5px solid #e0e7ef",
            borderTop: "2.5px solid #1e3a5f",
            borderRadius: "50%",
            animation: "spin 0.75s linear infinite",
            margin: "0 auto 14px",
          }} />

          <p style={{ color: "#546e7a", fontSize: "0.85rem", fontWeight: 500, letterSpacing: "0.01em" }}>
            Chargement…
          </p>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}