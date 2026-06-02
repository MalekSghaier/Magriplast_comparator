import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider }    from "./context/AuthContext";
import { SidebarProvider } from "./context/SidebarContext";
import ProtectedRoute      from "./components/auth/ProtectedRoute";
import AppLayout           from "./components/layout/AppLayout";
import LoginPage           from "./pages/LoginPage";
import RegisterPage        from "./pages/RegisterPage";
import UploadPage          from "./pages/UploadPage";
import JobsListPage        from "./pages/JobsListPage";
import JobPage             from "./pages/JobPage";
import ResultsPage         from "./pages/ResultsPage";
import ReviewPage          from "./pages/ReviewPage";

function ProtectedApp() {
  return (
    <SidebarProvider>
      <AppLayout>
        <Routes>
          <Route path="/"                element={<UploadPage />}  />
          <Route path="/jobs"            element={<JobsListPage />} />
          <Route path="/jobs/:jobId"     element={<JobPage />}     />
          <Route path="/results/:jobId"  element={<ResultsPage />} />
          <Route path="/review/:jobId"   element={<ReviewPage />}  />
          <Route path="*"               element={<Navigate to="/" replace />} />
        </Routes>
      </AppLayout>
    </SidebarProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Auth pages — no sidebar, no topbar */}
          <Route path="/login"    element={<LoginPage />}    />
          <Route path="/register" element={<RegisterPage />} />

          {/* App — sidebar + topbar + protected */}
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <ProtectedApp />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
