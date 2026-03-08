import { Navigate, Route, Routes } from "react-router-dom";
import MarketingLayout from "./layouts/MarketingLayout";
import AppLayout from "./layouts/AppLayout";
import AdminLayout from "./layouts/AdminLayout";

import Home from "./pages/home";
import Models from "./pages/models";
import Variables from "./pages/variables";
import Status from "./pages/status";
import Login from "./pages/login";
import AdminPerformance from "./pages/admin/performance";
import AdminUsage from "./pages/admin/usage";

import Viewer from "./pages/viewer";

export default function RouterApp() {
  return (
    <Routes>
      <Route element={<MarketingLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/models" element={<Models />} />
        <Route path="/variables" element={<Variables />} />
        <Route path="/status" element={<Status />} />
        <Route path="/login" element={<Login />} />
      </Route>

      <Route element={<AppLayout />}>
        <Route path="/viewer" element={<Viewer />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="/admin/performance" replace />} />
          <Route path="performance" element={<AdminPerformance />} />
          <Route path="usage" element={<AdminUsage />} />
        </Route>
      </Route>

      <Route path="/app" element={<Navigate to="/viewer" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
