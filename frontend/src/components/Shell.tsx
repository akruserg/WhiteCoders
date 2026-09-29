import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { fullDate, initials, pad, ROLE_NAME } from "../lib/format";
import type { RoleCode } from "../api/types";

interface NavItem { to: string; label: string; icon: ReactNode; end?: boolean }

const I = (d: string) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
);
const icons = {
  home: I("M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"),
  chart: I("M4 20V10M10 20V4M16 20v-7M22 20H2"),
  alert: I("M12 8v5M12 17h.01M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"),
  book: I("M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"),
  user: I("M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"),
  spark: I("M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"),
  play: I("M6 4l14 8-14 8z"),
  users: I("M17 21v-2a4 4 0 0 0-3-3.9M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2M16 3.1a4 4 0 0 1 0 7.8"),
  lock: I("M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4"),
  server: I("M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01"),
  phone: I("M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"),
  download: I("M12 3v12M7 10l5 5 5-5M4 21h16"),
  history: I("M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2"),
  shield: I("M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"),
};

const NAV: Record<RoleCode, { title: string; items: NavItem[] }> = {
  student: {
    title: "Кабинет обучающегося",
    items: [
      { to: "/student", label: "Мои задания", icon: icons.home, end: true },
      { to: "/student/progress", label: "Мой прогресс", icon: icons.chart },
      { to: "/student/errors", label: "Разбор ошибок", icon: icons.alert },
      { to: "/student/library", label: "Справочная база", icon: icons.book },
      { to: "/student/profile", label: "Профиль", icon: icons.user },
    ],
  },
  teacher: {
    title: "Кабинет преподавателя",
    items: [
      { to: "/teacher", label: "Обзор", icon: icons.home, end: true },
      { to: "/teacher/scenarios", label: "Сценарии", icon: icons.book },
      { to: "/teacher/generate", label: "ИИ-генерация", icon: icons.spark },
      { to: "/teacher/sessions", label: "Занятия", icon: icons.play },
      { to: "/teacher/monitor", label: "Мониторинг", icon: icons.users },
      { to: "/teacher/reports", label: "Отчёты", icon: icons.alert },
      { to: "/teacher/analytics", label: "Аналитика", icon: icons.chart },
      { to: "/teacher/groups", label: "Группы и роли", icon: icons.lock },
    ],
  },
  admin: {
    title: "Администрирование",
    items: [
      { to: "/admin", label: "Состояние системы", icon: icons.server, end: true },
      { to: "/admin/users", label: "Пользователи и роли", icon: icons.users },
      { to: "/admin/settings", label: "Телефония и настройки", icon: icons.phone },
      { to: "/admin/backups", label: "Резервное копирование", icon: icons.download },
      { to: "/admin/audit", label: "Журнал аудита", icon: icons.history },
      { to: "/admin/reports", label: "Отчёты", icon: icons.alert },
      { to: "/admin/security", label: "Безопасность", icon: icons.shield },
    ],
  },
};

export function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);
  return (
    <div className="clock">
      <div className="clock-date">{fullDate(now)}</div>
      <div className="clock-sub">{"УМЦ · АРМ 4 · доступен"}</div>
      <div className="clock-time">{pad(now.getHours())}:{pad(now.getMinutes())}<sup>:{pad(now.getSeconds())}</sup></div>
    </div>
  );
}

const TITLES: [RegExp, string, string][] = [
  [/^\/student$/, "Мои задания", "Назначенные преподавателем сценарии и занятия"],
  [/^\/student\/progress/, "Мой прогресс", "Баллы, скорость и типичные ошибки"],
  [/^\/student\/errors/, "Разбор ошибок", "Ваши ответы и эталон системы"],
  [/^\/student\/library/, "Справочная база", "Методические материалы и классификатор"],
  [/^\/student\/profile/, "Профиль", "Данные учётной записи"],
  [/^\/teacher$/, "Обзор", "Группы, занятия и рекомендации ИИ на сегодня"],
  [/^\/teacher\/scenarios/, "Сценарии", "Библиотека учебных сценариев"],
  [/^\/teacher\/generate/, "Генерация сценария (ИИ)", "Черновики сценариев на основе классификатора"],
  [/^\/teacher\/sessions/, "Занятия", "Планирование и запуск занятий"],
  [/^\/teacher\/monitor/, "Мониторинг занятия", "Ход занятия в реальном времени"],
  [/^\/teacher\/reports/, "Отчёты", "Отчёты по занятиям, группам и обучающимся"],
  [/^\/teacher\/analytics/, "Аналитика группы", "Тепловая карта ошибок и динамика"],
  [/^\/teacher\/groups/, "Группы и ролевая модель", "Состав групп и права доступа"],
  [/^\/admin$/, "Состояние системы", "Локальный учебный комплекс · мониторинг в реальном времени"],
  [/^\/admin\/users/, "Пользователи и роли", "Учётные записи и матрица прав"],
  [/^\/admin\/settings/, "Настройки системы", "Телефония, ИИ, резервное копирование, оповещения"],
  [/^\/admin\/backups/, "Резервное копирование", "Копии базы данных"],
  [/^\/admin\/audit/, "Журнал аудита", "Действия пользователей и проверка целостности"],
  [/^\/admin\/reports/, "Отчёты", "Системные отчёты: использование, аудит, ошибки и сбои"],
  [/^\/admin\/security/, "Безопасность", "Оповещения и состояние защиты"],
];

export default function Shell() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  if (!user) return null;
  const nav = NAV[user.role.code];
  const [, title, sub] = TITLES.find(([re]) => re.test(pathname)) ?? [null, "", ""];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">112</div>
          <div><b>Тренажёр ДДС</b><small>ГБУ «Система 112»</small></div>
        </div>
        <div className="nav-cap">{nav.title.toUpperCase()}</div>
        <nav>
          {nav.items.map((it) => (
            <NavLink key={it.to} to={it.to} end={it.end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
              {it.icon}<span>{it.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="spacer" />
        <div className="me">
          <div className="avatar" style={{ background: "#4a5157" }}>{initials(user.full_name)}</div>
          <div className="me-name"><b>{user.full_name}</b><small>{ROLE_NAME[user.role.code]}</small></div>
          <button className="logout" onClick={logout} title="Выйти" aria-label="Выйти">⎋</button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div><h1>{title}</h1><p>{sub}</p></div>
          <span className="spacer" />
          <Clock />
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
