import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, download } from "../../api/client";
import type { Paged, Session } from "../../api/types";
import { Badge, ErrorBox, Field, Loading, Panel } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

interface Report { id: string; kind: string; format: string; session_id: string | null; status: string; created_at: string; error: string | null }

const KINDS: Record<string, string> = {
  session: "Отчёт по занятию", student_progress: "Успеваемость обучающегося", group_progress: "Успеваемость группы",
  error_heatmap: "Тепловая карта ошибок", system_usage: "Использование системы", security_audit: "Аудит безопасности", system_errors: "Ошибки и сбои",
};

export default function Reports({ admin }: { admin?: boolean }) {
  const [sp] = useSearchParams();
  const { fail, notify } = useToast();
  const list = useLoad(() => api.get<Paged<Report>>("/reports", { per_page: 50 }), [], 8000);
  const sessions = useLoad(() => (admin ? Promise.resolve(null) : api.get<Paged<Session>>("/sessions", { per_page: 100 })));
  const [kind, setKind] = useState(admin ? "system_usage" : "session");
  const [format, setFormat] = useState("pdf");
  const [sessionId, setSessionId] = useState(sp.get("session") ?? "");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      await api.post("/reports", { kind, format, session_id: kind === "session" || kind === "error_heatmap" ? sessionId || null : null });
      notify("Отчёт формируется"); list.reload();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const kinds = admin ? ["system_usage", "security_audit", "system_errors"] : ["session", "group_progress", "student_progress", "error_heatmap"];

  return (
    <div className="grid-2" style={{ gridTemplateColumns: "1fr 1.6fr" }}>
      <Panel title="Новый отчёт">
        <div className="stack" style={{ gap: 14 }}>
          <Field label="Вид"><select className="select" value={kind} onChange={(e) => setKind(e.target.value)}>{kinds.map((k) => <option key={k} value={k}>{KINDS[k]}</option>)}</select></Field>
          {!admin && (kind === "session" || kind === "error_heatmap") && (
            <Field label="Занятие"><select className="select" value={sessionId} onChange={(e) => setSessionId(e.target.value)}><option value="">— выберите —</option>{sessions.data?.items.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></Field>
          )}
          <Field label="Формат"><select className="select" value={format} onChange={(e) => setFormat(e.target.value)}>{["pdf", "xlsx", "csv", "json"].map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}</select></Field>
          <button className="btn primary" disabled={busy || (kind === "session" && !sessionId)} onClick={create}>Сформировать</button>
        </div>
      </Panel>
      <Panel title="Мои отчёты">
        {list.loading ? <Loading /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : (
          <table className="tbl">
            <thead><tr><th>Отчёт</th><th>Формат</th><th>Создан</th><th>Статус</th><th /></tr></thead>
            <tbody>
              {list.data!.items.map((r) => (
                <tr key={r.id}>
                  <td>{KINDS[r.kind] ?? r.kind}</td><td>{r.format.toUpperCase()}</td><td>{shortDate(r.created_at)}</td>
                  <td><Badge tone={r.status === "ready" ? "green" : r.status === "failed" ? "red" : "yellow"}>{r.status === "ready" ? "Готов" : r.status === "failed" ? "Ошибка" : "Формируется"}</Badge></td>
                  <td style={{ textAlign: "right" }}>{r.status === "ready" && <button className="btn sm" onClick={() => download(`/reports/${r.id}/download`, `report.${r.format}`).catch(fail)}>Скачать</button>}</td>
                </tr>
              ))}
              {list.data!.items.length === 0 && <tr><td colSpan={5} className="empty">Отчётов пока нет</td></tr>}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
