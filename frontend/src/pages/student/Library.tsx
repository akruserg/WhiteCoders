import { useMemo, useState } from "react";
import { api, download } from "../../api/client";
import type { Category, Listed } from "../../api/types";
import { ErrorBox, Loading, Panel } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { useToast } from "../../lib/toast";

interface Material { id: string; title: string; mime_type: string; size_bytes: number; version: number; category_id: number | null }

export default function Library() {
  const { fail } = useToast();
  const mats = useLoad(() => api.get<Listed<Material>>("/materials"));
  const cats = useLoad(() => api.get<Listed<Category>>("/categories"));
  const [q, setQ] = useState("");

  const groups = useMemo(() => {
    const all = cats.data?.items ?? [];
    const roots = all.filter((c) => c.parent_id == null);
    return roots.map((r) => ({ ...r, types: all.filter((c) => c.parent_id === r.id) }));
  }, [cats.data]);
  const needle = q.trim().toLowerCase();

  return (
    <div className="grid-2" style={{ gridTemplateColumns: "1fr 1.4fr" }}>
      <Panel title="Методические материалы">
        {mats.loading && <Loading />}
        {mats.error && <ErrorBox error={mats.error} retry={mats.reload} />}
        {mats.data && mats.data.items.length === 0 && <div className="muted">Материалов пока нет</div>}
        <div className="stack" style={{ gap: 8 }}>
          {mats.data?.items.map((m) => (
            <div key={m.id} className="row" style={{ background: "#fff", padding: "10px 12px" }}>
              <div style={{ flex: 1 }}><b>{m.title}</b><div className="small muted">{m.mime_type} · {(m.size_bytes / 1024).toFixed(0)} КБ · v{m.version}</div></div>
              <button className="btn sm" onClick={() => download(`/materials/${m.id}/download`, m.title).catch(fail)}>Скачать</button>
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Классификатор происшествий">
        <input className="input" placeholder="Поиск по типам происшествий" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 12 }} />
        {cats.loading && <Loading />}
        <div className="stack" style={{ gap: 10, maxHeight: 520, overflow: "auto" }}>
          {groups.map((g) => {
            const types = needle ? g.types.filter((t) => t.name.toLowerCase().includes(needle)) : g.types;
            if (needle && types.length === 0) return null;
            return (
              <details key={g.id} open={!!needle} className="acc">
                <summary><b>{g.name}</b> <span className="muted small">· {types.length}</span></summary>
                <ul>{types.map((t) => <li key={t.id}>{t.name}{t.service_code && <span className="muted small"> · {t.service_code}</span>}</li>)}</ul>
              </details>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
