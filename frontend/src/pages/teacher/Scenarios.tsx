import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { Category, Listed, Paged, Scenario } from "../../api/types";
import { Badge, ErrorBox, Field, Loading, Modal, Panel, statusTone } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { DIFFICULTY, difficultyTone, fieldLabel, showValue } from "../../lib/format";
import { useToast } from "../../lib/toast";

const STATUS: Record<string, string> = { draft: "Черновик", pending_review: "На проверке", validated: "Утверждён", rejected: "Отклонён", archived: "В архиве" };
const ORIGIN: Record<string, string> = { ai: "ИИ", manual: "Вручную", imported: "Импорт", student: "От обучающегося" };

export default function Scenarios() {
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") ?? "";
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Scenario | null>(null);
  const cats = useLoad(() => api.get<Listed<Category>>("/categories"));
  const list = useLoad(() => api.get<Paged<Scenario>>("/scenarios", { status, q, per_page: 100 }), [status, q]);
  const catName = (id: number) => cats.data?.items.find((c) => c.id === id)?.name ?? `#${id}`;

  return (
    <div className="stack">
      <Panel>
        <div className="row">
          <input className="input" style={{ maxWidth: 320 }} placeholder="Поиск по названию" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="select" style={{ maxWidth: 200 }} value={status} onChange={(e) => setSp(e.target.value ? { status: e.target.value } : {})}>
            <option value="">Все статусы</option>{Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <span className="spacer" /><span className="muted small">Всего: {list.data?.total ?? "…"}</span>
        </div>
      </Panel>
      {list.loading ? <Loading /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : (
        <div className="panel" style={{ padding: 0 }}>
          <table className="tbl">
            <thead><tr><th>Сценарий</th><th>Категория</th><th>Сложность</th><th>Источник</th><th>Норматив</th><th>Статус</th></tr></thead>
            <tbody>
              {list.data!.items.map((s) => (
                <tr key={s.id} className="click" onClick={() => setOpen(s)}>
                  <td><b>{s.title}</b></td><td>{catName(s.category_id)}</td>
                  <td><Badge tone={difficultyTone(s.difficulty)}>{DIFFICULTY[s.difficulty]}</Badge></td>
                  <td><Badge tone={s.origin === "ai" ? "accent" : undefined}>{ORIGIN[s.origin]}</Badge></td>
                  <td>{s.time_limit_sec ? `${s.time_limit_sec} с` : "—"}</td>
                  <td><Badge tone={statusTone(s.status)}>{STATUS[s.status] ?? s.status}</Badge></td>
                </tr>
              ))}
              {list.data!.items.length === 0 && <tr><td colSpan={6} className="empty">Сценариев не найдено</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {open && <ScenarioModal scenario={open} onClose={() => setOpen(null)} onChanged={() => { setOpen(null); list.reload(); }} />}
    </div>
  );
}

export function ScenarioModal({ scenario, onClose, onChanged }: { scenario: Scenario; onClose: () => void; onChanged: () => void }) {
  const { notify, fail } = useToast();
  const [ref, setRef] = useState<Record<string, any>>(scenario.reference_card ?? {});
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const legend = scenario.legend ?? {};

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { await fn(); notify(done); onChanged(); } catch (e) { fail(e); } finally { setBusy(false); }
  };

  return (
    <Modal title={scenario.title} onClose={onClose} footer={
      <>
        <button className="btn danger" disabled={busy} onClick={() => window.confirm("Архивировать сценарий?") && run(() => api.del(`/scenarios/${scenario.id}`), "Сценарий в архиве")}>Архивировать</button>
        <span style={{ flex: 1 }} />
        <button className="btn" disabled={busy} onClick={() => run(() => api.patch(`/scenarios/${scenario.id}`, { reference_card: ref }), "Эталон сохранён")}>Сохранить эталон</button>
        <button className="btn green" disabled={busy} onClick={() => run(() => api.post(`/scenarios/${scenario.id}/validate`, { full: true, comment }), "Сценарий утверждён")}>Утвердить</button>
      </>
    }>
      <div className="stack" style={{ gap: 14 }}>
        <div><div className="small muted">Легенда</div><div className="pre">{legend.description ?? legend.text ?? ""}{(legend.dialog ?? []).map((l: string) => `\n— ${l}`).join("")}</div></div>
        {legend.hints?.length ? <div className="small"><b>Подсказки:</b> {legend.hints.join("; ")}</div> : null}
        <div>
          <div className="small muted" style={{ marginBottom: 6 }}>Эталонная карточка (можно править)</div>
          <div className="stack" style={{ gap: 8 }}>
            {Object.keys(ref).map((k) => (
              <Field key={k} label={fieldLabel(k)}><input className="input" value={showValue(ref[k]) === "—" ? "" : String(ref[k])} onChange={(e) => setRef({ ...ref, [k]: e.target.value })} /></Field>
            ))}
          </div>
        </div>
        <Field label="Комментарий к правке (ИИ учтёт или сохранится в истории)">
          <div className="row"><input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Например: добавить пострадавших" />
            <button className="btn" disabled={busy || comment.trim().length < 3} onClick={() => run(() => api.post(`/scenarios/${scenario.id}/corrections`, { comment, apply_now: true }), "Правка применена")}>Применить</button></div>
        </Field>
      </div>
    </Modal>
  );
}
