import { useState } from "react";
import { api } from "../../api/client";
import type { Paged, Session } from "../../api/types";
import { BarChart } from "../../components/charts";
import { ErrorBox, Loading, Panel, Stat, Bar } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { ERROR_KINDS, fieldLabel, num } from "../../lib/format";

export default function Analytics() {
  const sessions = useLoad(() => api.get<Paged<Session>>("/sessions", { per_page: 100 }));
  const [sid, setSid] = useState("");
  const heat = useLoad(() => api.get("/analytics/heatmap", { session_id: sid }), [sid]);
  const results = useLoad(() => (sid ? api.get(`/sessions/${sid}/results`) : Promise.resolve(null)), [sid]);
  const fa = useLoad(() => api.get("/analytics/forecast-accuracy", { session_id: sid }), [sid]);

  const h = heat.data;
  const cell = (f: string, k: string) => h?.cells.find((c: any) => c.field_key === f && c.kind === k)?.count ?? 0;
  const max = Math.max(1, ...(h?.cells ?? []).map((c: any) => c.count));
  const students: any[] = results.data?.students ?? [];

  return (
    <div className="stack">
      <div className="row">
        <select className="select" style={{ maxWidth: 380 }} value={sid} onChange={(e) => setSid(e.target.value)}>
          <option value="">Все мои занятия</option>{sessions.data?.items.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
      </div>
      {results.data && (
        <div className="grid-4">
          <Stat label="Карточек" value={results.data.summary.attempts} />
          <Stat label="Средний балл" value={num(results.data.summary.avg_score, 1)} tone="green" />
          <Stat label="Зачёт" value={`${num(results.data.summary.pass_rate)}%`} />
          <Stat label="Просрочки" value={results.data.summary.time_overruns} tone="red" />
        </div>
      )}
      <div className="grid-2e">
        <Panel title="Тепловая карта ошибок">
          {heat.loading ? <Loading /> : heat.error ? <ErrorBox error={heat.error} retry={heat.reload} /> : h.fields.length === 0 ? <div className="muted">Ошибок пока нет</div> : (
            <div className="heat" style={{ gridTemplateColumns: `140px repeat(${h.kinds.length}, 1fr)` }}>
              <div className="cell head" />{h.kinds.map((k: string) => <div key={k} className="cell head">{ERROR_KINDS[k]?.label ?? k}</div>)}
              {h.fields.map((f: string) => (
                <div key={f} style={{ display: "contents" }}>
                  <div className="cell head" style={{ textAlign: "left" }}>{fieldLabel(f)}</div>
                  {h.kinds.map((k: string) => { const v = cell(f, k); return <div key={k} className="cell" style={{ background: v ? `rgba(229,50,45,${0.12 + 0.75 * (v / max)})` : "#fff", color: v / max > .55 ? "#fff" : undefined }}>{v || ""}</div>; })}
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title={sid ? "Баллы обучающихся" : "Выберите занятие"}>
          {students.length > 0 ? <BarChart items={students.map((s) => ({ label: s.full_name.split(" ")[0], value: s.avg_score }))} /> : <div className="muted">Выберите занятие, чтобы увидеть результаты по обучающимся</div>}
        </Panel>
      </div>
      {students.length > 0 && (
        <Panel title="Результаты по обучающимся">
          <table className="tbl"><thead><tr><th>Обучающийся</th><th>Карточек</th><th>Ср. балл</th><th>Зачёт</th><th>Ср. время</th><th>Просрочки</th></tr></thead>
            <tbody>{students.map((s) => <tr key={s.user_id}><td>{s.full_name}</td><td>{s.attempts}</td><td><div className="row"><div style={{ width: 100 }}><Bar value={s.avg_score} tone={s.avg_score >= 70 ? "green" : "red"} /></div>{num(s.avg_score, 1)}</div></td><td>{s.passed}</td><td>{s.avg_duration_sec} с</td><td>{s.time_overruns}</td></tr>)}</tbody></table>
        </Panel>
      )}
      {fa.data?.available && <Panel title="Точность прогноза ИИ"><div className="row" style={{ gap: 30 }}><span>MAE: <b>{num(fa.data.mae, 1)}</b></span><span>Попадание: <b>{num(fa.data.hit_rate * 100)}%</b></span><span>Наблюдений: <b>{fa.data.n}</b></span><span>Надёжность: <b>{fa.data.reliability}</b></span></div></Panel>}
    </div>
  );
}
