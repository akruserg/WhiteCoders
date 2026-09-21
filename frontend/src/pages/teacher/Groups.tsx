import { useState } from "react";
import { api } from "../../api/client";
import type { Paged, User } from "../../api/types";
import { ErrorBox, Field, Loading, Modal, Panel } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { useToast } from "../../lib/toast";

interface Group { id: string; name: string; teacher_id: string | null; members: string[] }

export default function Groups() {
  const { fail, notify } = useToast();
  const groups = useLoad(() => api.get<{ items: Group[] }>("/groups"));
  const users = useLoad(() => api.get<Paged<User>>("/users", { role: "student", per_page: 200 }));
  const matrix = useLoad(() => api.get("/roles/matrix").catch(() => null));
  const [sel, setSel] = useState<Group | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const nameOf = (id: string) => users.data?.items.find((u) => u.id === id)?.full_name ?? id.slice(0, 8);
  const current = groups.data?.items.find((g) => g.id === sel?.id) ?? null;

  const create = async () => {
    try { await api.post("/groups", { name }); setCreating(false); setName(""); groups.reload(); notify("Группа создана"); } catch (e) { fail(e); }
  };
  const add = async (uid: string) => { try { await api.post(`/groups/${current!.id}/members`, { user_ids: [uid] }); groups.reload(); } catch (e) { fail(e); } };
  const remove = async (uid: string) => { try { await api.del(`/groups/${current!.id}/members/${uid}`); groups.reload(); } catch (e) { fail(e); } };

  if (groups.loading) return <Loading />;
  if (groups.error) return <ErrorBox error={groups.error} retry={groups.reload} />;

  return (
    <div className="grid-2e">
      <Panel title="Учебные группы" aside={<button className="btn sm primary" onClick={() => setCreating(true)}>+ Группа</button>}>
        <div className="stack" style={{ gap: 6 }}>
          {groups.data!.items.map((g) => (
            <button key={g.id} className={`pick${current?.id === g.id ? " on" : ""}`} onClick={() => setSel(g)}><b>{g.name}</b><span className="spacer" /><span className="muted small">{g.members.length} уч.</span></button>
          ))}
          {groups.data!.items.length === 0 && <div className="muted">Групп пока нет</div>}
        </div>
      </Panel>
      <div className="stack">
        <Panel title={current ? `Состав: ${current.name}` : "Состав группы"}>
          {!current ? <div className="muted">Выберите группу слева</div> : (
            <>
              <div className="stack" style={{ gap: 6 }}>
                {current.members.map((id) => <div key={id} className="row" style={{ background: "#fff", padding: "8px 12px" }}><span style={{ flex: 1 }}>{nameOf(id)}</span><button className="btn sm" onClick={() => remove(id)}>Убрать</button></div>)}
                {current.members.length === 0 && <div className="muted">В группе нет обучающихся</div>}
              </div>
              <Field label="Добавить обучающегося">
                <select className="select" value="" onChange={(e) => e.target.value && add(e.target.value)} style={{ marginTop: 12 }}>
                  <option value="">— выберите —</option>{users.data?.items.filter((u) => !current.members.includes(u.id)).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
                </select>
              </Field>
            </>
          )}
        </Panel>
        {matrix.data && (
          <Panel title="Ролевая модель (справочно)">
            <table className="tbl"><thead><tr><th>Роль</th><th>Прав</th></tr></thead>
              <tbody>{matrix.data.roles.map((r: any) => <tr key={r.code}><td>{r.name ?? r.code}</td><td>{r.permissions.length}</td></tr>)}</tbody></table>
          </Panel>
        )}
      </div>
      {creating && <Modal title="Новая группа" onClose={() => setCreating(false)} footer={<button className="btn primary" disabled={!name.trim()} onClick={create}>Создать</button>}><Field label="Название"><input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="ДДС-2026-А" /></Field></Modal>}
    </div>
  );
}
