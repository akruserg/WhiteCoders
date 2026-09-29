import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import type { Paged, Scenario, Session, Listed } from "../../api/types";
import { BarChart } from "../../components/charts";
import { Badge, ErrorBox, Loading, Panel, Stat, Bar, statusTone } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { num } from "../../lib/format";
import { useToast } from "../../lib/toast";

export default function Overview() {
  const nav = useNavigate();
  const { fail } = useToast();
  const sessions = useLoad(() => api.get<Paged<Session>>("/sessions", { per_page: 50 }), [], 10000);
  const pending = useLoad(() => api.get<Paged<Scenario>>("/scenarios", { status: "pending_review", per_page: 6 }));
  const overview = useLoad(() => api.get("/analytics/overview"));
  const heat = useLoad(() => api.get("/analytics/heatmap"));
  const insights = useLoad(() => api.get<Listed<{ id: string; title: string; body: string; confidence: number | null }>>("/insights"));

  if (sessions.loading) return <Loading />;
  if (sessions.error) return <ErrorBox error={sessions.error} retry={sessions.reload} />;

  const list = sessions.data?.items ?? [];
  const running = list.filter((s) => s.status === "running");
  const planned = list.filter((s) => s.status === "planned");
  const ov = overview.data;

  const start = async (id: string) => {
    try { await api.post(`/sessions/${id}/start`); nav(`/teacher/monitor?session=${id}`); } catch (e) { fail(e); }
  };

  // ошибки по полям из тепловой карты → «типичные ошибки»
  const byField = new Map<string, number>();
  (heat.data?.cells ?? []).forEach((c: any) => byField.set(c.field_key, (byField.get(c.field_key) ?? 0) + c.count));
  const topErrors = [...byField.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
  const maxErr = Math.max(1, ...topErrors.map(([, v]) => v));

  return (
    <div className="stack">
      <div className="grid-4">
        <Stat label="Активные занятия" value={running.length} sub={`запланировано: ${planned.length}`} />
        <Stat label="Средний балл" value={ov ? num(ov.attempts.avg_score) : "—"} sub={ov ? `зачёт ${num(ov.attempts.pass_rate)}%` : ""} tone="green" />
        <Stat label="Сценарии на проверке" value={pending.data?.total ?? "—"} sub="ждут утверждения" tone="red" />
        <Stat label="Просрочки тайминга" value={ov ? ov.attempts.time_overruns : "—"} sub={ov ? `из ${ov.attempts.attempts} карточек` : ""} tone="red" />
      </div>

      <div className="grid-2e">
        <Panel title="Идёт занятие">
          {running.length === 0 && <div className="muted">Сейчас нет активных занятий</div>}
          {running.map((s) => (
            <div key={s.id} style={{ background: "#fff", padding: 14, marginBottom: 10 }}>
              <div className="row"><div style={{ flex: 1 }}><b style={{ fontSize: 15 }}>{s.title}</b><div className="small muted">{s.participants.length} участников · норматив {s.time_limit_sec ?? "из сценария"} с</div></div>
                <Link className="btn primary" to={`/teacher/monitor?session=${s.id}`}>Открыть мониторинг</Link></div>
            </div>
          ))}
          {planned[0] && (
            <div style={{ background: "#fff", padding: 14 }}>
              <div className="small muted">Следующее занятие</div>
              <div className="row" style={{ marginTop: 4 }}><b style={{ flex: 1 }}>{planned[0].title} <span className="muted small">· {planned[0].participants.length} уч.</span></b>
                <button className="btn outline sm" onClick={() => start(planned[0].id)}>Запустить</button></div>
            </div>
          )}
        </Panel>
        <Panel title="Успеваемость" aside={<span className="small muted">средний балл</span>}>
          {ov ? <BarChart items={[{ label: "Средний", value: ov.attempts.avg_score }, { label: "Зачёт %", value: ov.attempts.pass_rate }]} /> : <Loading />}
        </Panel>
      </div>

      <div className="grid-2e">
        <Panel title="Сценарии на проверке" aside={<Link to="/teacher/scenarios?status=pending_review" className="small">все →</Link>}>
          {pending.data?.items.length === 0 && <div className="muted">Нет сценариев, ожидающих проверки</div>}
          <table className="tbl"><tbody>
            {pending.data?.items.map((s) => (
              <tr key={s.id}><td>{s.title}</td><td><Badge tone={s.origin === "ai" ? "accent" : undefined}>{s.origin === "ai" ? "ИИ" : "Вручную"}</Badge></td><td><Badge tone={statusTone(s.status)}>На проверке</Badge></td></tr>
            ))}
          </tbody></table>
        </Panel>
        <Panel title="Инсайты ИИ по типичным ошибкам">
          <div className="stack" style={{ gap: 12 }}>
            {topErrors.length === 0 && (insights.data?.items.length ?? 0) === 0 && <div className="muted">Данных пока недостаточно</div>}
            {topErrors.map(([k, v]) => <div key={k}><div className="row small"><span>Поле «{k}»: ошибок {v}</span></div><Bar value={(v / maxErr) * 100} tone="red" /></div>)}
            {insights.data?.items.slice(0, 3).map((i) => <div key={i.id} className="small"><b>{i.title}</b><div className="muted">{i.body}</div></div>)}
          </div>
        </Panel>
      </div>
    </div>
  );
}
