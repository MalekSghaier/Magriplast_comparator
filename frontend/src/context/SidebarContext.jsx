import { createContext, useContext, useState } from "react";

const SidebarContext = createContext(null);

export function SidebarProvider({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <SidebarContext.Provider value={{
      collapsed,
      mobileOpen,
      toggleCollapse: () => setCollapsed(c => !c),
      toggleMobile:   () => setMobileOpen(o => !o),
      closeMobile:    () => setMobileOpen(false),
    }}>
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  const ctx = useContext(SidebarContext);
  if (!ctx) throw new Error("useSidebar must be inside <SidebarProvider>");
  return ctx;
}