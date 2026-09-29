import { api } from "../../api/client";
import { ErrorBox, Loading, Panel, Stat, Bar } from "../../components/ui";
import { LineChart } from "../../components/charts";
import { useLoad } from "../../lib/hooks";
import { dayMonth, ERROR_KINDS, fieldLabel, num } from "../../lib/format";

const RELIABILITY: Record<string, string> = { insufficient: "недостаточно данных", low: "низкая", medium: "средняя", high: "высокая" };
const TREND: Record<string, string> = { up: "растёт", down: "снижается", flat: "стабильно" };

export default function Progress() {
  const { data, error, loading, reload } = useLoad(() => api.get("/me/progress"));
  if (loading) return <Loading />;
  if (error || !data) return <ErrorBox error={error ?? new Error("Нет данных")} retry={reload} />;

  const { summary, errors, timeline, forecast, by_category, forecast_accuracy: fa } = data;
  const kinds = Object.entries(errors.by_kind as Record<string, number>);
  const maxKind = Math.max(1, ...kinds.map(([, v]) => v));
  const maxField = Math.max(1, ...errors.by_field.map((f: any) => f.count));

  return (
    <div className="stack">
      <div className="grid-4">
        <Stat label="Карточек оценено" value={summary.attempts} />
        <Stat label="Средний балл" value={num(summary.avg_score, 1)} tone="green" sub={`зачёт ${num(summary.pass_rate)}%`} />
        <Stat label="Среднее время" value={`${num(summary.avg_duration_sec)} с`} />
        <Stat label="Просрочки" value={summary.time_overruns} tone={summary.time_overruns ? "red" : "green"} />
      </div>
      <div className="grid-2">
        <Panel title="Динамика по занятиям">
          {timeline.length ? <LineChart points={timeline.map((t: any) => t.avg_score)} labels={timeline.map((t: any) => (t.started_at ? dayMonth(t.started_at) : ""))} /> : <div className="muted">Нет данных</div>}
        </Panel>
        <Panel title="Прогноз ИИ">
          {forecast.available ? (
            <div className="stack" style={{ gap: 8 }}>
              <div>Следующий результат: <b style={{ fontSize: 22 }}>{num(forecast.next_score, 1)}</b></div>
              <div className="small muted">Тренд: {TREND[forecast.trend] ?? forecast.trend}{forecast.sessions_to_pass ? ` · до зачёта ~${forecast.sessions_to_pass} зан.` : ""}</div>
              {fa?.available && <div className="small muted">Точность прогноза: {RELIABILITY[fa.reliability] ?? fa.reliability} (MAE {num(fa.mae, 1)})</div>}
            </div>
          ) : <div className="muted small">{forecast.reason ?? "Прогноз пока недоступен"}</div>}
        </Panel>
      </div>
      <div className="grid-2e">
        <Panel title="Ошибки по типам">
          {kinds.length === 0 && <div className="muted">Ошибок нет</div>}
          <div className="stack" style={{ gap: 10 }}>
            {kinds.map(([k, v]) => <div key={k}><div className="row small"><span>{ERROR_KINDS[k]?.label ?? k}</span><span className="spacer" /><b>{v}</b></div><Bar value={(v / maxKind) * 100} tone="accent" /></div>)}
          </div>
          <h3 className="panel-title" style={{ marginTop: 20 }}>Проблемные поля</h3>
          <div className="stack" style={{ gap: 10 }}>
            {errors.by_field.map((f: any) => <div key={f.field_key}><div className="row small"><span>{fieldLabel(f.field_key)}</span><span className="spacer" /><b>{f.count}</b></div><Bar value={(f.count / maxField) * 100} tone="yellow" /></div>)}
          </div>
        </Panel>
        <Panel title="Результаты по категориям">
          {by_category.length === 0 && <div className="muted">Нет данных</div>}
          <div className="stack" style={{ gap: 10 }}>
            {by_category.map((c: any) => <div key={c.code}><div className="row small"><span>{c.name}</span><span className="spacer" /><b>{num(c.avg_score, 1)}</b><span className="muted">· {c.attempts}</span></div><Bar value={c.avg_score} tone={c.avg_score >= 70 ? "green" : "red"} /></div>)}
          </div>
        </Panel>
      </div>
    </div>
  );
}
