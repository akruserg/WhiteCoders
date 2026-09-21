import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Paged, Session, Listed } from "../../api/types";
import { Badge, ErrorBox, Loading, Panel, Stat } from "../../components/ui";
import { LineChart } from "../../components/charts";
import { useLoad } from "../../lib/hooks";
import { dayMonth, num } from "../../lib/format";

const MODE: Record<string, string> = { cards: "заполнение карточек", card_actions: "карточка + действия", mixed: "смешанный" };

export default function Tasks() {
  const sessions = useLoad(() => api.get<Paged<Session>>("/sessions", { per_page: 50 }), [], 15000);
  const progress = useLoad(() => api.get("/me/progress"));
  const recs = useLoad(() => api.get<Listed<{ id: string; title: string; body: string }>>("/me/recommendations"));

  if (sessions.loading) return <Loading />;
  if (sessions.error) return <ErrorBox error={sessions.error} retry={sessions.reload} />;

  const list = (sessions.data?.items ?? []).filter((s) => s.status !== "finished");
  const sum = progress.data?.summary;
  const timeline: { started_at: string | null; avg_score: number }[] = progress.data?.timeline ?? [];

  return (
    <div className="stack">
      <div className="grid-4">
        <Stat label="Назначено заданий" value={list.length} sub={`${list.filter((s) => s.status === "running").length} идёт сейчас`} />
        <Stat label="Выполнено" value={sum?.attempts ?? "—"} sub="карточек всего" />
        <Stat label="Средний балл" value={sum ? num(sum.avg_score) : "—"} sub={sum ? `зачёт: ${num(sum.pass_rate)}%` : ""} tone="green" />
        <Stat label="Среднее время карточки" value={sum ? `${num(sum.avg_duration_sec)} с` : "—"} sub={`просрочек: ${sum?.time_overruns ?? 0}`} tone={sum?.time_overruns ? "red" : "green"} />
      </div>

      <div className="grid-2">
        <Panel title="Доступные модули" aside={<span className="small muted">сортировка: по сроку</span>}>
          {list.length === 0 && <div className="empty">Преподаватель пока не назначил занятий</div>}
          <div className="stack" style={{ gap: 10 }}>
            {list.map((s) => (
              <div key={s.id} className={`module ${s.status === "running" ? "yellow" : "gray"}`}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <b>{s.title}</b>
                  <div className="small muted" style={{ marginTop: 4 }}>{MODE[s.mode]} · {s.time_limit_sec ? `норматив ${s.time_limit_sec} с` : "норматив из сценария"}{s.channel === "voip" ? " · голосовой канал" : ""}</div>
                </div>
                {s.status === "running" ? <Badge tone="green">Идёт</Badge> : <Badge tone="blue">Запланировано</Badge>}
                {s.status === "running"
                  ? <Link className="btn primary" to={`/arm/${s.id}`}>Начать</Link>
                  : <span className="btn" style={{ opacity: .55, cursor: "default" }} title="Ожидает запуска преподавателем">🔒</span>}
              </div>
            ))}
          </div>
        </Panel>

        <div className="stack">
          <Panel title="Рекомендации ИИ">
            {recs.data?.items.length ? (
              <ul className="recs">{recs.data.items.slice(0, 4).map((r) => <li key={r.id}><b>{r.title}</b><br /><span className="muted">{r.body}</span></li>)}</ul>
            ) : <div className="muted small">Рекомендации появятся после первых занятий</div>}
          </Panel>
          <Panel title="Динамика баллов" aside={<span className="small muted">{timeline.length} занятий</span>}>
            {timeline.length ? (
              <LineChart points={timeline.map((t) => t.avg_score)} labels={timeline.map((t) => (t.started_at ? dayMonth(t.started_at) : ""))} />
            ) : <div className="muted small">Пока нет оценённых карточек</div>}
          </Panel>
        </div>
      </div>
    </div>
  );
}
