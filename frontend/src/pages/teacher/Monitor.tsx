import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Paged, Session } from "../../api/types";
import { Badge, Bar, ErrorBox, Loading, Stat } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { initials, num, shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

interface MonItem { attempt_id: string; user_id: string; full_name: string | null; seq: number; status: string; score: number | null; passed: boolean | null; duration_ms: number | null; time_limit_sec: number; issued_at: string }
interface Monitor { session_id: string; status: string; attempts_total: number; in_progress: number; avg_score: number | null; items: MonItem[] }

const ST: Record<string, [string, "green" | "red" | "blue" | "yellow" | undefined]> = {
  issued: ["Звонит", "yellow"], in_progress: ["Заполняет", "blue"], submitted: ["Проверка", "yellow"], evaluated: ["Заполнена", "green"], expired: ["Пропущена", "red"],
};

export default function MonitorPage() {
  const [sp, setSp] = useSearchParams();
  const { fail, notify } = useToast();
  const sessions = useLoad(() => api.get<Paged<Session>>("/sessions", { status: "running", per_page: 50 }), [], 10000);
  const id = sp.get("session") ?? sessions.data?.items[0]?.id ?? "";
  const mon = useLoad(() => (id ? api.get<Monitor>(`/sessions/${id}/monitor`) : Promise.resolve(null)), [id], 2000);
  const session = sessions.data?.items.find((s) => s.id === id);

  if (sessions.loading) return <Loading />;
  if (sessions.error) return <ErrorBox error={sessions.error} retry={sessions.reload} />;
  if (!id) return <div className="panel empty">Сейчас нет идущих занятий. <Link to="/teacher/sessions">Запустить занятие →</Link></div>;

  const m = mon.data;
  // последняя карточка каждого обучающегося
  const last = new Map<string, MonItem>();
  m?.items.forEach((it) => { if (!last.has(it.user_id)) last.set(it.user_id, it); });
  const rows = [...last.values()];
  const done = rows.filter((r) => r.status === "evaluated").length;
  const overrun = rows.filter((r) => (r.duration_ms ?? 0) / 1000 > r.time_limit_sec).length;

  const finish = async () => {
    if (!window.confirm("Завершить занятие? Незавершённые карточки будут закрыты.")) return;
    try { await api.post(`/sessions/${id}/finish`); notify("Занятие завершено"); sessions.reload(); } catch (e) { fail(e); }
  };

  return (
    <div className="stack">
      {(sessions.data?.items.length ?? 0) > 1 && (
        <select className="select" style={{ maxWidth: 360 }} value={id} onChange={(e) => setSp({ session: e.target.value })}>
          {sessions.data!.items.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
      )}
      <div className="grid-4">
        <Stat label="Занятие" value={<span style={{ fontSize: 18 }}>{session?.title ?? "—"}</span>} sub={session?.started_at ? `с ${shortDate(session.started_at)}` : ""} />
        <Stat label="Завершили карточку" value={`${done} / ${session?.participants.length ?? rows.length}`} sub="участников" tone="green" />
        <Stat label="Средний балл" value={num(m?.avg_score)} sub={`карточек: ${m?.attempts_total ?? 0}`} />
        <Stat label="Просрочки" value={overrun} sub="участников" tone="red" />
      </div>
      <div className="panel" style={{ padding: 0 }}>
        <table className="tbl">
          <thead><tr><th>Обучающийся</th><th>Карточка</th><th>Таймер</th><th>Результат</th><th>Статус</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const sec = Math.round((r.status === "in_progress" || r.status === "issued" ? Date.now() - new Date(r.issued_at).getTime() : r.duration_ms ?? 0) / (r.status === "in_progress" || r.status === "issued" ? 1000 : 1000));
              const over = sec > r.time_limit_sec;
              const [label, tone] = ST[r.status] ?? [r.status, undefined];
              return (
                <tr key={r.user_id}>
                  <td><div className="row"><span className="avatar">{initials(r.full_name ?? "?")}</span><b>{r.full_name}</b></div></td>
                  <td>№ {r.seq}</td>
                  <td><span className={`monitor-timer${over ? " over" : ""}`}>{String(Math.floor(sec / 60)).padStart(2, "0")}:{String(sec % 60).padStart(2, "0")}</span></td>
                  <td style={{ width: 220 }}>{r.score != null ? <div className="row"><div style={{ flex: 1 }}><Bar value={r.score} tone={r.passed ? "green" : "red"} /></div><b>{num(r.score)}</b></div> : <span className="muted">—</span>}</td>
                  <td><Badge tone={tone}>{label}</Badge></td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={5} className="empty">Обучающиеся ещё не получили карточки</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="row"><span className="muted small">Данные обновляются каждые 2 секунды</span><span className="spacer" /><button className="btn dark" onClick={finish}>✕ Завершить занятие</button></div>
    </div>
  );
}
