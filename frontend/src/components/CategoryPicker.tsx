import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Category, Listed } from "../api/types";
import { useLoad } from "../lib/hooks";

/** Поиск и множественный выбор типов происшествий из классификатора (1281 тип). */
export default function CategoryPicker({ value, onChange, single }: { value: number[]; onChange: (ids: number[]) => void; single?: boolean }) {
  const cats = useLoad(() => api.get<Listed<Category>>("/categories"));
  const [q, setQ] = useState("");
  const all = useMemo(() => {
    const items = cats.data?.items ?? [];
    const parents = new Set(items.map((c) => c.parent_id).filter((x): x is number => x != null));
    return items.filter((c) => !parents.has(c.id) || c.parent_id != null);
  }, [cats.data]);
  const byId = useMemo(() => new Map(all.map((c) => [c.id, c])), [all]);
  const needle = q.trim().toLowerCase();
  const shown = (needle ? all.filter((c) => c.name.toLowerCase().includes(needle)) : all.filter((c) => c.parent_id != null)).slice(0, 40);

  const toggle = (id: number) => onChange(single ? [id] : value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);

  return (
    <div className="catpick">
      <div className="quick" style={{ marginBottom: 6 }}>
        {value.map((id) => <button type="button" key={id} className="chip on" onClick={() => toggle(id)}>{byId.get(id)?.name ?? id} ✕</button>)}
        {value.length === 0 && <span className="muted small">{single ? "тип не выбран" : "все категории (не выбрано)"}</span>}
      </div>
      <input className="input" placeholder="Найти тип происшествия…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="catlist">
        {cats.loading && <div className="muted small" style={{ padding: 8 }}>Загрузка классификатора…</div>}
        {shown.map((c) => (
          <button type="button" key={c.id} className={value.includes(c.id) ? "on" : ""} onClick={() => toggle(c.id)}>{c.name}</button>
        ))}
        {!cats.loading && shown.length === 0 && <div className="muted small" style={{ padding: 8 }}>Ничего не найдено</div>}
      </div>
    </div>
  );
}
