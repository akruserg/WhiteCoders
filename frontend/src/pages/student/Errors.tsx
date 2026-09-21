import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { AttemptResult, Paged } from "../../api/types";
import { Badge, ErrorBox, Loading, Panel, Bar } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { ERROR_KINDS, fieldLabel, num, shortDate, showValue } from "../../lib/format";

interface Row { attempt_id: string; seq: number; score: number | null; passed: boolean | null; delta_sec: number; errors_count: number; submitted_at: string | null; time_limit_sec: number; duration_ms: number | null }

export default function Errors() {
  const list = useLoad(() => api.get<Paged<Row>>("/me/attempts", { per_page: 50 }));
  const [sp] = useSearchParams();
  const [sel, setSel] = useState<string | null>(sp.get("attempt"));
  useEffect(() => { if (!sel && list.data?.items[0]) setSel(list.data.items[0].attempt_id); }, [list.data, sel]);
  const detail = useLoad(() => (sel ? api.get<AttemptResult>(`/attempts/${sel}`) : Promise.resolve(null)), [sel]);

  if (list.loading) return <Loading />;
  if (list.error) return <ErrorBox error={list.error} retry={list.reload} />;
  if (!list.data?.items.length) return <div className="panel empty">Пока нет оценённых карточек. Выполните задание, и здесь появится разбор.</div>;

  const d = detail.data;
  return (
    <div className="grid-2" style={{ gridTemplateColumns: "1fr 2fr" }}>
      <Panel title="Мои карточки" aside={<span className="small muted">{list.data.total}</span>}>
        <div className="stack" style={{ gap: 6 }}>
          {list.data.items.map((r) => (
            <button key={r.attempt_id} className={`pick${sel === r.attempt_id ? " on" : ""}`} onClick={() => setSel(r.attempt_id)}>
              <b>Карточка {r.seq}</b>
              <span className="small muted">{shortDate(r.submitted_at)}</span>
              <span className="spacer" />
              <Badge tone={r.passed ? "green" : "red"}>{num(r.score, 0)}</Badge>
            </button>
          ))}
        </div>
      </Panel>

      <div className="stack">
        {detail.loading && <Loading />}
        {detail.error && <ErrorBox error={detail.error} retry={detail.reload} />}
        {d && (
          <>
            <Panel title={`Результат карточки ${d.seq}`}>
              <div className="row" style={{ alignItems: "baseline", gap: 14 }}>
                <span style={{ fontSize: 44, fontWeight: 500 }}>{num(d.score, 0)}</span><span className="muted">/ 100</span>
                <Badge tone={d.passed ? "green" : "red"}>{d.passed ? "Зачёт" : "Не зачтено"}</Badge>
                <span className="spacer" />
                <div className="small" style={{ textAlign: "right" }}>
                  <div style={{ color: d.delta_sec > 0 ? "var(--c-red)" : "var(--c-green)", fontWeight: 500 }}>Время: {num((d.duration_ms ?? 0) / 1000, 0)} с</div>
                  <div className="muted">норматив {d.time_limit_sec} с{d.delta_sec > 0 ? ` (+${d.delta_sec} с)` : ""}</div>
                </div>
              </div>
              <div style={{ marginTop: 12 }}><Bar value={d.score ?? 0} tone="accent" /></div>
              {d.expert_comment && <div className="note"><b>Комментарий преподавателя:</b> {d.expert_comment}</div>}
            </Panel>

            <Panel title="Замечания">
              {d.details_hidden && <div className="muted">Идёт аттестация: подробный разбор откроется после завершения занятия.</div>}
              {!d.details_hidden && d.errors.length === 0 && <div className="muted">Замечаний нет. Отличная работа!</div>}
              {d.errors.length > 0 && (
                <table className="tbl">
                  <thead><tr><th>Поле</th><th>Тип</th><th>Описание</th><th>Ваш ответ</th><th>Эталон</th></tr></thead>
                  <tbody>
                    {d.errors.map((e, i) => (
                      <tr key={i}>
                        <td>{fieldLabel(e.field_key)}</td>
                        <td><Badge tone={ERROR_KINDS[e.kind]?.tone}>{ERROR_KINDS[e.kind]?.label ?? e.kind}</Badge></td>
                        <td>{e.message}</td>
                        <td>{showValue(e.actual)}</td>
                        <td>{showValue(e.expected)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}
