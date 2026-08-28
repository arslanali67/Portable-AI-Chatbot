import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./components/RequireAuth";
import AppLayout from "./layout/AppLayout";
import ChatbotDetailPage from "./pages/ChatbotDetailPage";
import ChatbotsPage from "./pages/ChatbotsPage";
import DashboardPage from "./pages/DashboardPage";
import LoginPage from "./pages/LoginPage";
import OrganizationsPage from "./pages/OrganizationsPage";
import OrganizationSettingsPage from "./pages/OrganizationSettingsPage";
import ProvidersPage from "./pages/ProvidersPage";
import RegisterPage from "./pages/RegisterPage";
import WidgetPreviewPage from "./pages/WidgetPreviewPage";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/organizations/:organizationId/chatbots/:chatbotId/widget-preview"
            element={
              <RequireAuth>
                <WidgetPreviewPage />
              </RequireAuth>
            }
          />
          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/organizations" element={<OrganizationsPage />} />
            <Route path="/organizations/:organizationId" element={<ChatbotsPage />} />
            <Route
              path="/organizations/:organizationId/settings"
              element={<OrganizationSettingsPage />}
            />
            <Route path="/organizations/:organizationId/chatbots/:chatbotId/*" element={<ChatbotDetailPage />} />
            <Route path="/providers" element={<ProvidersPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}