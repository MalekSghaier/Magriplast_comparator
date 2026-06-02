import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { loginUser, registerUser, refreshTokens, getMe } from "../api/auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const token = localStorage.getItem("access_token");
      if (!token) { setLoading(false); return; }

      try {
        const me = await getMe();
        setUser(me);
      } catch {
        // try refresh
        try {
          const rt = localStorage.getItem("refresh_token");
          if (!rt) throw new Error();
          const tokens = await refreshTokens(rt);
          localStorage.setItem("access_token", tokens.access_token);
          localStorage.setItem("refresh_token", tokens.refresh_token);
          const me = await getMe();
          setUser(me);
        } catch {
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const login = useCallback(async (email, password) => {
    const tokens = await loginUser(email, password);
    localStorage.setItem("access_token", tokens.access_token);
    localStorage.setItem("refresh_token", tokens.refresh_token);
    const me = await getMe();
    setUser(me);
    return me;
  }, []);

  const register = useCallback(async (email, full_name, password) => {
    const registeredUser = await registerUser(email, full_name, password);
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
    return registeredUser;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside <AuthProvider>");
  return ctx;
}
