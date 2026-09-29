import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import type { Scenario } from "../../api/types";
import CategoryPicker from "../../components/CategoryPicker";
import { Badge, Field, Panel } from "../../components/ui";
import { DIFFICULTY } from "../../lib/format";
import { useToast } from "../../lib/toast";
import { ScenarioModal } from "./Scenarios";

export default function Generate() {
  const { fail, notify } = useToast();
  const [cats, setCats] = useState<number[]>([]);
  const [count, setCount] = useState(3);
  const [difficulty, setDifficulty] = useState(2);
  const [hints, setHints] = useState("");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  const [items, setItems] = useState<Scenario[]>([]);
  const [open, setOpen] = useState<Scenario | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (cats.length === 0) { notify("Выберите хотя бы один тип происшествия"); return; }
    setBusy(true);
    try {
      const res = await api.post<{ items: Scenario[] }>("/scenarios/generate", { category_ids: cats, count, difficulty, hints, location });
      setItems(res.items);
      notify(`Сформировано черновиков: ${res.items.length}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "ai_disabled") notify("ИИ-модуль отключён: включите его в настройках системы (ai.enabled)");
      else fail(err);
    } finally { setBusy(false); }
  };

  return (
    <div className="grid-2" style={{ gridTemplateColumns: "1fr 1.2fr" }}>
      <Panel title="Параметры генерации">
        <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
          <Field label="Типы происшествий"><CategoryPicker value={cats} onChange={setCats} /></Field>
          <div className="form-grid">
            <Field label="Количество"><input className="input" type="number" min={1} max={50} value={count} onChange={(e) => setCount(+e.target.value)} /></Field>
            <Field label="Сложность"><select className="select" value={difficulty} onChange={(e) => setDifficulty(+e.target.value)}>{[1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d} — {DIFFICULTY[d]}</option>)}</select></Field>
            <Field label="Место события (район, объект)"><input className="input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Например: Троицкий АО" /></Field>
          </div>
          <Field label="Пожелания к сценарию"><textarea className="textarea" value={hints} onChange={(e) => setHints(e.target.value)} placeholder="Например: заявитель взволнован, адрес называет не сразу" /></Field>
          <button className="btn primary" disabled={busy} style={{ alignSelf: "flex-start", padding: "11px 22px" }}>{busy ? "Генерация… это может занять несколько минут" : "Сгенерировать"}</button>
        </form>
      </Panel>
      <Panel title="Результат" aside={<span className="small muted">черновики уходят на проверку преподавателю</span>}>
        {items.length === 0 && <div className="muted">Здесь появятся сформированные сценарии. Откройте каждый, чтобы проверить эталон и утвердить.</div>}
        <div className="stack" style={{ gap: 8 }}>
          {items.map((s) => (
            <div key={s.id} className="row" style={{ background: "#fff", padding: "10px 14px" }}>
              <div style={{ flex: 1 }}><b>{s.title}</b><div className="small muted">сложность {s.difficulty} · норматив {s.time_limit_sec ?? "по профилю"} с</div></div>
              <Badge tone="yellow">На проверке</Badge><button className="btn sm" onClick={() => setOpen(s)}>Открыть</button>
            </div>
          ))}
        </div>
      </Panel>
      {open && <ScenarioModal scenario={open} onClose={() => setOpen(null)} onChanged={() => { setOpen(null); }} />}
    </div>
  );
}
