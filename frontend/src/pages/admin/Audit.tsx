import { useState } from "react";
import { api } from "../../api/client";
import type { Paged } from "../../api/types";
import { Badge, ErrorBox, Loading } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

interface Entry { id: number; ts: string; role_code: string | null; action: string; object_type: string | null; object_id: string | null; ip: string | null; payload: any }

export default function Audit() {
  const { fail } = useToast();
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const list = useLoad(() => api.get<Paged<Entry>>("/system/audit", { page, per_page: 30, action }), [page, action]);
  const [verify, setVerify] = useState<any>(null);
  const check = async () => { try { setVerify(await api.get("/system/audit/verify")); } catch (e) { fail(e); } };

  return (
    <div className="stack">
      <div className="row">
        <input className="input" style={{ maxWidth: 280 }} placeholder="Действие, например auth.login" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} />
        <span className="spacer" />
        {verify && <Badge tone={verify.intact ? "green" : "red"}>{verify.intact ? "Цепочка целостна" : "Целостность нарушена"} · проверено {verify.checked ?? ""}</Badge>}
        <button className="btn" onClick={check}>Проверить целостность</button>
      </div>
      {list.loading ? <Loading /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : (
        <div className="panel" style={{ padding: 0 }}>
          <table className="tbl"><thead><tr><th>Время</th><th>Роль</th><th>Действие</th><th>Объект</th><th>IP</th><th>Детали</th></tr></thead>
            <tbody>{list.data!.items.map((e) => (
              <tr key={e.id}><td style={{ whiteSpace: "nowrap" }}>{shortDate(e.ts)}</td><td>{e.role_code ?? "—"}</td><td><b>{e.action}</b></td><td>{e.object_type ?? ""} <span className="muted small">{e.object_id?.slice(0, 8)}</span></td><td>{e.ip}</td><td className="small muted" style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.payload ? JSON.stringify(e.payload) : ""}</td></tr>
            ))}</tbody></table>
        </div>
      )}
      <div className="row"><button className="btn sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Назад</button><span className="muted small">стр. {page} из {list.data?.pages ?? 1}</span><button className="btn sm" disabled={page >= (list.data?.pages ?? 1)} onClick={() => setPage(page + 1)}>Вперёд →</button></div>
    </div>
  );
}
