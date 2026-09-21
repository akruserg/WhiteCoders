import { api } from "../../api/client";
import type { Paged } from "../../api/types";
import { Badge, ErrorBox, Loading } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

interface Alert { id: number; component: string; severity: string; status: string; title: string; details: any; occurrences: number; last_seen_at: string }

export default function Security() {
  const { fail } = useToast();
  const list = useLoad(() => api.get<Paged<Alert>>("/system/alerts", { per_page: 100 }), [], 10000);
  const act = async (id: number, a: "ack" | "resolve") => { try { await api.post(`/system/alerts/${id}/${a}`, {}); list.reload(); } catch (e) { fail(e); } };
  if (list.loading) return <Loading />;
  if (list.error) return <ErrorBox error={list.error} retry={list.reload} />;
  return (
    <div className="panel" style={{ padding: 0 }}>
      <table className="tbl"><thead><tr><th>Оповещение</th><th>Компонент</th><th>Уровень</th><th>Повторов</th><th>Последнее</th><th>Статус</th><th /></tr></thead>
        <tbody>{list.data!.items.map((a) => (
          <tr key={a.id}><td><b>{a.title}</b></td><td>{a.component}</td><td><Badge tone={a.severity === "critical" || a.severity === "error" ? "red" : "yellow"}>{a.severity}</Badge></td><td>{a.occurrences}</td><td>{shortDate(a.last_seen_at)}</td>
            <td><Badge tone={a.status === "resolved" ? "green" : a.status === "acknowledged" ? "blue" : "red"}>{a.status}</Badge></td>
            <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>{a.status === "open" && <button className="btn sm" onClick={() => act(a.id, "ack")}>Принять</button>} {a.status !== "resolved" && <button className="btn sm" onClick={() => act(a.id, "resolve")}>Закрыть</button>}</td></tr>
        ))}{list.data!.items.length === 0 && <tr><td colSpan={7} className="empty">Оповещений нет — система в норме</td></tr>}</tbody></table>
    </div>
  );
}
