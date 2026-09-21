import { Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { useAuth, homePath } from "./auth/AuthContext";
import Shell from "./components/Shell";
import { Modal } from "./components/ui";
import type { RoleCode } from "./api/types";
import Login from "./pages/Login";
import Workstation from "./pages/arm/Workstation";
import Tasks from "./pages/student/Tasks";
import Progress from "./pages/student/Progress";
import Errors from "./pages/student/Errors";
import Library from "./pages/student/Library";
import Profile from "./pages/student/Profile";
import Overview from "./pages/teacher/Overview";
import Scenarios from "./pages/teacher/Scenarios";
import Generate from "./pages/teacher/Generate";
import Sessions from "./pages/teacher/Sessions";
import MonitorPage from "./pages/teacher/Monitor";
import Reports from "./pages/teacher/Reports";
import Analytics from "./pages/teacher/Analytics";
import Groups from "./pages/teacher/Groups";
import Health from "./pages/admin/Health";
import Users from "./pages/admin/Users";
import Settings from "./pages/admin/Settings";
import Backups from "./pages/admin/Backups";
import Audit from "./pages/admin/Audit";
import Security from "./pages/admin/Security";
import { useToast } from "./lib/toast";

function Guard({ role, children }: { role: RoleCode; children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center-fill">Загрузка…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role.code !== role) return <Navigate to={homePath(user.role.code)} replace />;
  return <>{children}</>;
}

/** Согласие на обработку персональных данных (152-ФЗ): без него работа в системе недоступна. */
function ConsentGate() {
  const { user, reload, logout } = useAuth();
  const { fail } = useToast();
  if (!user?.consent_required) return null;
  const accept = async () => { try { await api.post("/auth/consent"); await reload(); } catch (e) { fail(e); } };
  return (
    <Modal title="Согласие на обработку персональных данных" onClose={() => {}} footer={<><button className="btn" onClick={logout}>Отказаться и выйти</button><button className="btn primary" onClick={accept}>Согласен</button></>}>
      <p style={{ lineHeight: 1.5 }}>Для работы в учебном комплексе необходимо ваше согласие на обработку персональных данных (ФИО, результаты обучения, журнал действий) в соответствии с Федеральным законом № 152-ФЗ. Данные используются только внутри защищённого контура.</p>
    </Modal>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  return (
    <>
      <ConsentGate />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/arm/:sessionId" element={<Guard role="student"><Workstation /></Guard>} />

        <Route path="/student" element={<Guard role="student"><Shell /></Guard>}>
          <Route index element={<Tasks />} />
          <Route path="progress" element={<Progress />} />
          <Route path="errors" element={<Errors />} />
          <Route path="library" element={<Library />} />
          <Route path="profile" element={<Profile />} />
        </Route>

        <Route path="/teacher" element={<Guard role="teacher"><Shell /></Guard>}>
          <Route index element={<Overview />} />
          <Route path="scenarios" element={<Scenarios />} />
          <Route path="generate" element={<Generate />} />
          <Route path="sessions" element={<Sessions />} />
          <Route path="monitor" element={<MonitorPage />} />
          <Route path="reports" element={<Reports />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="groups" element={<Groups />} />
        </Route>

        <Route path="/admin" element={<Guard role="admin"><Shell /></Guard>}>
          <Route index element={<Health />} />
          <Route path="users" element={<Users />} />
          <Route path="settings" element={<Settings />} />
          <Route path="backups" element={<Backups />} />
          <Route path="audit" element={<Audit />} />
          <Route path="reports" element={<Reports admin />} />
          <Route path="security" element={<Security />} />
        </Route>

        <Route path="*" element={loading ? <div className="center-fill">Загрузка…</div> : <Navigate to={user ? homePath(user.role.code) : "/login"} replace />} />
      </Routes>
    </>
  );
}
