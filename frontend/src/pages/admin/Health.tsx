import { api } from "../../api/client";
import { Badge, Bar, ErrorBox, Loading, Panel, Stat } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

const COMP: Record<string, string> = { api: "API (учебный интерфейс)", database: "База данных PostgreSQL", voip: "SIP-сервер (VoIP)", ai: "ИИ-модуль (генерация и оценка)", reports: "Сервис отчётов" };
const TONE: Record<string, "green" | "yellow" | "red" | undefined> = { up: "green", disabled: undefined, degraded: "yellow", down: "red" };
const LABEL: Record<string, string> = { up: "Работает", disabled: "Отключён", degraded: "Предупреждение", down: "Недоступен" };

export default function Health() {
  const { fail, notify } = useToast();
  const health = useLoad(() => api.get("/system/health"), [], 10000);
  const metrics = useLoad(() => api.get("/system/metrics"), [], 10000);
  const services = useLoad(() => api.get<{ items: { name: string; enabled: boolean; controllable: boolean }[] }>("/system/services"));
  const events = useLoad(() => api.get("/system/events", { per_page: 8 }), [], 10000);

  if (health.loading || metrics.loading) return <Loading />;
  if (health.error) return <ErrorBox error={health.error} retry={health.reload} />;
  const m = metrics.data, comps = Object.entries<any>(health.data.components);
  const voip = health.data.components.voip;

  const toggle = async (name: string, enabled: boolean) => {
    try { await api.post(`/system/services/${name}/${enabled ? "stop" : "start"}`); notify(`Сервис ${name}: ${enabled ? "остановлен" : "запущен"}`); services.reload(); health.reload(); } catch (e) { fail(e); }
  };

  return (
    <div className="stack">
      <div className="grid-4">
        <Stat label="Сессий сейчас" value={`${m.active_sessions} / ${m.capacity.max_concurrent_sessions}`} sub="пропускная способность" />
        <Stat label="Карточек в работе" value={m.concurrent_attempts} sub="одновременно" />
        <Stat label="Задержка VoIP" value={voip?.rtt_ms != null ? `${Math.round(voip.rtt_ms)} мс` : "—"} sub={`порог ${m.capacity.voip_latency_limit_ms} мс`} tone="green" />
        <Stat label="Ошибок за 24 ч" value={m.errors_24h} sub={`открытых оповещений: ${m.open_alerts}`} tone={m.errors_24h ? "red" : "green"} />
      </div>
      <div className="grid-2">
        <Panel title="Сервисы" aside={<Badge tone={TONE[health.data.status]}>{health.data.status === "up" ? "Всё в норме" : "Есть замечания"}</Badge>}>
          <table className="tbl"><thead><tr><th>Компонент</th><th>Состояние</th><th>Подробности</th></tr></thead>
            <tbody>{comps.map(([k, v]) => (
              <tr key={k}><td>{COMP[k] ?? k}</td><td><Badge tone={TONE[v.status]}>{LABEL[v.status] ?? v.status}</Badge></td><td className="small muted">{v.detail ?? v.error ?? v.model ?? (v.formats ? v.formats.join(", ") : "")}</td></tr>
            ))}</tbody></table>
          <h3 className="panel-title" style={{ marginTop: 18 }}>Управление сервисами</h3>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {services.data?.items.filter((s) => s.controllable).map((s) => (
              <button key={s.name} className="btn sm" onClick={() => toggle(s.name, s.enabled)}>{s.enabled ? "■ Остановить" : "▶ Запустить"} {s.name}</button>
            ))}
          </div>
        </Panel>
        <Panel title="Нагрузка на сервер" aside={<span className="small muted">сейчас</span>}>
          <div className="stack" style={{ gap: 14 }}>
            <div><div className="row small"><span>Диск (свободно)</span><span className="spacer" /><b>{m.disk.free_gb} из {m.disk.total_gb} ГБ</b></div><Bar value={100 - (m.disk.free_gb / m.disk.total_gb) * 100} tone="yellow" /></div>
            {m.load_avg && <div><div className="row small"><span>Load average (1 мин)</span><span className="spacer" /><b>{m.load_avg[0].toFixed(2)}</b></div><Bar value={Math.min(100, m.load_avg[0] * 25)} /></div>}
            <div><div className="row small"><span>Пользователи (лимит {m.capacity.max_users})</span></div></div>
          </div>
        </Panel>
      </div>
      <Panel title="Журнал событий">
        <div className="stack" style={{ gap: 8 }}>
          {events.data?.items.map((e: any) => <div key={e.id} className="row small"><span className="muted" style={{ width: 130 }}>{shortDate(e.ts)}</span><Badge tone={e.level === "error" || e.level === "critical" ? "red" : e.level === "warning" ? "yellow" : "blue"}>{e.component}</Badge><span>{e.message}</span></div>)}
          {events.data?.items.length === 0 && <div className="muted">Событий нет</div>}
        </div>
      </Panel>
    </div>
  );
}
