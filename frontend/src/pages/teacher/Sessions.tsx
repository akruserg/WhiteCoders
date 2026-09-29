import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { Paged, Session, User } from "../../api/types";
import CategoryPicker from "../../components/CategoryPicker";
import { Badge, ErrorBox, Field, Loading, Modal, statusTone } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

const STATUS: Record<string, string> = { planned: "Запланировано", running: "Идёт", finished: "Завершено" };
const MODE: Record<string, string> = { cards: "Заполнение карточек", card_actions: "Карточка + действия", mixed: "Смешанный" };

export default function Sessions() {
  const nav = useNavigate();
  const { fail, notify } = useToast();
  const list = useLoad(() => api.get<Paged<Session>>("/sessions", { per_page: 100 }), [], 10000);
  const [creating, setCreating] = useState(false);

  const act = async (id: string, action: "start" | "finish") => {
    try {
      await api.post(`/sessions/${id}/${action}`);
      notify(action === "start" ? "Занятие запущено" : "Занятие завершено");
      if (action === "start") nav(`/teacher/monitor?session=${id}`); else list.reload();
    } catch (e) { fail(e); }
  };

  return (
    <div className="stack">
      <div className="row"><span className="muted">Занятий: {list.data?.total ?? "…"}</span><span className="spacer" /><button className="btn primary" onClick={() => setCreating(true)}>+ Новое занятие</button></div>
      {list.loading ? <Loading /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : (
        <div className="panel" style={{ padding: 0 }}>
          <table className="tbl">
            <thead><tr><th>Занятие</th><th>Режим</th><th>Участников</th><th>Канал</th><th>Создано</th><th>Статус</th><th /></tr></thead>
            <tbody>
              {list.data!.items.map((s) => (
                <tr key={s.id}>
                  <td><b>{s.title}</b>{s.settings?.attestation && <> <Badge tone="accent">аттестация</Badge></>}</td>
                  <td>{MODE[s.mode]}</td><td>{s.participants.length}</td><td>{s.channel === "voip" ? "голос" : "текст"}</td><td>{shortDate(s.created_at)}</td>
                  <td><Badge tone={statusTone(s.status)}>{STATUS[s.status]}</Badge></td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {s.status === "planned" && <button className="btn primary sm" onClick={() => act(s.id, "start")}>Запустить</button>}
                    {s.status === "running" && <><Link className="btn sm" to={`/teacher/monitor?session=${s.id}`}>Мониторинг</Link> <button className="btn sm" onClick={() => window.confirm("Завершить занятие? Незавершённые карточки будут закрыты.") && act(s.id, "finish")}>Завершить</button></>}
                    {s.status === "finished" && <Link className="btn sm" to={`/teacher/reports?session=${s.id}`}>Отчёт</Link>}
                  </td>
                </tr>
              ))}
              {list.data!.items.length === 0 && <tr><td colSpan={7} className="empty">Занятий пока нет. Создайте первое.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {creating && <CreateSession onClose={() => setCreating(false)} onCreated={() => { setCreating(false); list.reload(); }} />}
    </div>
  );
}

function CreateSession({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { fail, notify } = useToast();
  const groups = useLoad(() => api.get<{ items: { id: string; name: string; members: string[] }[] }>("/groups"));
  const students = useLoad(() => api.get<Paged<User>>("/users", { role: "student", per_page: 200 }));
  const [f, setF] = useState({ title: "", mode: "cards", question_source: "generated", group_id: "", time_limit_sec: "", channel: "text", difficulty_min: 1, difficulty_max: 5, attest: false, pass_score: 75, min_attempts: 3 });
  const [cats, setCats] = useState<number[]>([]);
  const [people, setPeople] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: unknown) => setF((s) => ({ ...s, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/sessions", {
        title: f.title, mode: f.mode, question_source: f.question_source, channel: f.channel,
        group_id: f.group_id || null, participant_ids: people, category_ids: cats,
        difficulty_min: f.difficulty_min, difficulty_max: f.difficulty_max,
        time_limit_sec: f.time_limit_sec ? +f.time_limit_sec : null,
        attestation: f.attest ? { pass_score: f.pass_score, min_attempts: f.min_attempts, certificate: true } : null,
      });
      notify("Занятие создано"); onCreated();
    } catch (err) { fail(err); } finally { setBusy(false); }
  };

  return (
    <Modal title="Новое занятие" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Отмена</button><button form="new-session" className="btn primary" disabled={busy}>Создать</button></>}>
      <form id="new-session" className="stack" style={{ gap: 14 }} onSubmit={submit}>
        <Field label="Название"><input className="input" required value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="Например: Пожары в жилом секторе" /></Field>
        <div className="form-grid">
          <Field label="Режим"><select className="select" value={f.mode} onChange={(e) => set("mode", e.target.value)}>{Object.entries(MODE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Канал"><select className="select" value={f.channel} onChange={(e) => set("channel", e.target.value)}><option value="text">Текстовый диалог</option><option value="voip">Голос (VoIP)</option></select></Field>
          <Field label="Группа"><select className="select" value={f.group_id} onChange={(e) => set("group_id", e.target.value)}><option value="">— без группы —</option>{groups.data?.items.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.members.length})</option>)}</select></Field>
          <Field label="Норматив на карточку, с (пусто: из сценария)"><input className="input" type="number" min={5} max={3600} value={f.time_limit_sec} onChange={(e) => set("time_limit_sec", e.target.value)} /></Field>
          <Field label="Сложность от"><input className="input" type="number" min={1} max={5} value={f.difficulty_min} onChange={(e) => set("difficulty_min", +e.target.value)} /></Field>
          <Field label="Сложность до"><input className="input" type="number" min={1} max={5} value={f.difficulty_max} onChange={(e) => set("difficulty_max", +e.target.value)} /></Field>
        </div>
        <Field label="Дополнительно добавить обучающихся">
          <select className="select" multiple size={5} value={people} onChange={(e) => setPeople([...e.target.selectedOptions].map((o) => o.value))}>
            {students.data?.items.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.username})</option>)}
          </select>
        </Field>
        <Field label="Типы происшествий"><CategoryPicker value={cats} onChange={setCats} /></Field>
        <label className="row"><input type="checkbox" checked={f.attest} onChange={(e) => set("attest", e.target.checked)} /> Режим аттестации (без подсказок, с сертификатом)</label>
        {f.attest && <div className="form-grid">
          <Field label="Проходной балл"><input className="input" type="number" min={0} max={100} value={f.pass_score} onChange={(e) => set("pass_score", +e.target.value)} /></Field>
          <Field label="Минимум карточек"><input className="input" type="number" min={1} value={f.min_attempts} onChange={(e) => set("min_attempts", +e.target.value)} /></Field>
        </div>}
      </form>
    </Modal>
  );
}
