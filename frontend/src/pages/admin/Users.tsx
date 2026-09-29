import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import type { Paged, User } from "../../api/types";
import { Badge, ErrorBox, Field, Loading, Modal, Panel } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { ROLE_NAME, shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

const ROLE_BY_ID: Record<number, string> = {};

export default function Users() {
  const { fail, notify } = useToast();
  const [tab, setTab] = useState<"users" | "roles">("users");
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const list = useLoad(() => api.get<Paged<User & { role_code?: string }>>("/users", { q, role, per_page: 100 }), [q, role]);
  const roles = useLoad(() => api.get<{ items: { id: number; code: string }[] }>("/roles"));
  roles.data?.items.forEach((r) => { ROLE_BY_ID[r.id] = r.code; });
  const [creating, setCreating] = useState(false);

  const act = async (u: User, action: "block" | "unblock" | "reset-password") => {
    try {
      if (action === "reset-password") {
        const np = window.prompt("Новый пароль (не менее 10 символов):");
        if (!np) return;
        await api.post(`/users/${u.id}/reset-password`, { new_password: np });
      } else await api.post(`/users/${u.id}/${action}`);
      notify("Готово"); list.reload();
    } catch (e) { fail(e); }
  };

  return (
    <div className="stack">
      <div className="tabs"><button className={tab === "users" ? "on" : ""} onClick={() => setTab("users")}>Пользователи</button><button className={tab === "roles" ? "on" : ""} onClick={() => setTab("roles")}>Права ролей</button></div>
      {tab === "roles" ? <RolesMatrix /> : (
        <>
          <div className="row">
            <input className="input" style={{ maxWidth: 300 }} placeholder="Поиск по ФИО или логину" value={q} onChange={(e) => setQ(e.target.value)} />
            <select className="select" style={{ maxWidth: 200 }} value={role} onChange={(e) => setRole(e.target.value)}><option value="">Все роли</option>{Object.entries(ROLE_NAME).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <span className="spacer" /><button className="btn primary" onClick={() => setCreating(true)}>+ Пользователь</button>
          </div>
          {list.loading ? <Loading /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : (
            <div className="panel" style={{ padding: 0 }}>
              <table className="tbl">
                <thead><tr><th>ФИО</th><th>Логин</th><th>Роль</th><th>Последний вход</th><th>Статус</th><th /></tr></thead>
                <tbody>{list.data!.items.map((u) => (
                  <tr key={u.id}>
                    <td><b>{u.full_name}</b></td><td>{u.username}</td><td>{ROLE_NAME[ROLE_BY_ID[u.role_id]] ?? u.role_id}</td><td>{shortDate(u.last_login_at)}</td>
                    <td>{u.anonymized_at ? <Badge>Обезличен</Badge> : u.is_blocked ? <Badge tone="red">Заблокирован</Badge> : u.is_active ? <Badge tone="green">Активен</Badge> : <Badge>Отключён</Badge>}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button className="btn sm" onClick={() => act(u, u.is_blocked ? "unblock" : "block")}>{u.is_blocked ? "Разблокировать" : "Заблокировать"}</button>{" "}
                      <button className="btn sm" onClick={() => act(u, "reset-password")}>Сбросить пароль</button>
                    </td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </>
      )}
      {creating && <CreateUser onClose={() => setCreating(false)} onCreated={() => { setCreating(false); list.reload(); }} />}
    </div>
  );
}

function CreateUser({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { fail, notify } = useToast();
  const [f, setF] = useState({ username: "", full_name: "", password: "", role_code: "student", email: "", mfa_enabled: false });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post("/users", { ...f, email: f.email || null }); notify("Пользователь создан"); onCreated(); } catch (err) { fail(err); }
  };
  const set = (k: string, v: unknown) => setF((s) => ({ ...s, [k]: v }));
  return (
    <Modal title="Новый пользователь" onClose={onClose} footer={<button form="new-user" className="btn primary">Создать</button>}>
      <form id="new-user" className="stack" style={{ gap: 12 }} onSubmit={submit}>
        <Field label="ФИО"><input className="input" required value={f.full_name} onChange={(e) => set("full_name", e.target.value)} /></Field>
        <div className="form-grid">
          <Field label="Логин"><input className="input" required minLength={3} value={f.username} onChange={(e) => set("username", e.target.value)} /></Field>
          <Field label="Роль"><select className="select" value={f.role_code} onChange={(e) => set("role_code", e.target.value)}>{Object.entries(ROLE_NAME).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Пароль (не менее 10 символов)"><input className="input" type="password" required minLength={10} value={f.password} onChange={(e) => set("password", e.target.value)} /></Field>
          <Field label="Почта"><input className="input" type="email" value={f.email} onChange={(e) => set("email", e.target.value)} /></Field>
        </div>
        <label className="row"><input type="checkbox" checked={f.mfa_enabled} onChange={(e) => set("mfa_enabled", e.target.checked)} /> Двухфакторная аутентификация</label>
      </form>
    </Modal>
  );
}

function RolesMatrix() {
  const { fail, notify } = useToast();
  const m = useLoad(() => api.get("/roles/matrix"));
  if (m.loading) return <Loading />;
  if (m.error) return <ErrorBox error={m.error} retry={m.reload} />;
  const { permissions, roles } = m.data as { permissions: { code: string; description: string }[]; roles: any[] };

  const toggle = async (role: any, code: string) => {
    const set = new Set<string>(role.permissions);
    set.has(code) ? set.delete(code) : set.add(code);
    try { await api.put(`/roles/${role.code}/permissions`, { permissions: [...set], comment: "изменено в интерфейсе" }); notify("Права обновлены"); m.reload(); }
    catch (e) { fail(e); }
  };
  return (
    <Panel title="Матрица прав ролей" aside={<span className="small muted">изменения действуют сразу</span>}>
      <table className="tbl">
        <thead><tr><th>Право</th>{roles.map((r) => <th key={r.code} style={{ textAlign: "center" }}>{r.name ?? r.code}</th>)}</tr></thead>
        <tbody>{permissions.map((p) => (
          <tr key={p.code}>
            <td><b>{p.code}</b><div className="small muted">{p.description}</div></td>
            {roles.map((r) => {
              const locked = r.forbidden?.includes(p.code) || r.must_have?.includes(p.code);
              return <td key={r.code} style={{ textAlign: "center" }}><input type="checkbox" checked={r.permissions.includes(p.code)} disabled={locked} onChange={() => toggle(r, p.code)} title={locked ? "Ограничено правилами ТЗ" : ""} /></td>;
            })}
          </tr>
        ))}</tbody>
      </table>
    </Panel>
  );
}
