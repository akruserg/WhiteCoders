import { api } from "../../api/client";
import type { Paged } from "../../api/types";
import { Badge, ErrorBox, Loading } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

interface Backup { id: string; started_at: string; finished_at: string | null; status: string; kind: string; is_automatic: boolean; size_bytes: number | null; error: string | null }

export default function Backups() {
  const { fail, notify } = useToast();
  const list = useLoad(() => api.get<Paged<Backup>>("/system/backups", { per_page: 50 }), [], 5000);
  const run = async () => { try { await api.post("/system/backups", { kind: "full" }); notify("Резервное копирование запущено"); list.reload(); } catch (e) { fail(e); } };
  return (
    <div className="stack">
      <div className="row"><span className="muted">Копий: {list.data?.total ?? "…"}</span><span className="spacer" /><button className="btn primary" onClick={run}>Создать копию сейчас</button></div>
      {list.loading ? <Loading /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : (
        <div className="panel" style={{ padding: 0 }}>
          <table className="tbl"><thead><tr><th>Начало</th><th>Окончание</th><th>Тип</th><th>Размер</th><th>Статус</th></tr></thead>
            <tbody>{list.data!.items.map((b) => (
              <tr key={b.id}><td>{shortDate(b.started_at)}</td><td>{shortDate(b.finished_at)}</td><td>{b.is_automatic ? "автоматическая" : "ручная"}</td><td>{b.size_bytes ? `${(b.size_bytes / 1048576).toFixed(1)} МБ` : "—"}</td>
                <td><Badge tone={b.status === "success" || b.status === "ok" ? "green" : b.status === "failed" ? "red" : "yellow"}>{b.status}</Badge>{b.error && <div className="err-text">{b.error}</div>}</td></tr>
            ))}{list.data!.items.length === 0 && <tr><td colSpan={5} className="empty">Копий пока нет</td></tr>}</tbody></table>
        </div>
      )}
    </div>
  );
}
