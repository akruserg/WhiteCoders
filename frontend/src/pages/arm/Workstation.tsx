import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import type { Attempt, AttemptResult, CallMessage, NextCard, Paged, Session } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { Clock } from "../../components/Shell";
import { Modal } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { ERROR_KINDS, fieldLabel, num, shortDate, showValue } from "../../lib/format";
import { useToast } from "../../lib/toast";
import CardEditor, { type Answer } from "./CardEditor";
import { ACTION_BY_FIELD } from "./constants";

type Phase = "journal" | "ringing" | "card" | "result";

/** Рабочее место оператора (АРМ-112): журнал → входящий вызов → карточка → результат. */
export default function Workstation() {
  const { sessionId = "" } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const { fail, notify } = useToast();

  const session = useLoad(() => api.get<Session>(`/sessions/${sessionId}`), [sessionId], 10000);
  const journal = useLoad(() => api.get<Paged<Attempt>>(`/sessions/${sessionId}/attempts`, { per_page: 50 }), [sessionId]);

  const [phase, setPhase] = useState<Phase>("journal");
  const [card, setCard] = useState<NextCard | null>(null);
  const [answer, setAnswer] = useState<Answer>({});
  const [actions, setActions] = useState<{ type: string }[]>([]);
  const [messages, setMessages] = useState<CallMessage[]>([]);
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [buffered, setBuffered] = useState(false);
  const [busy, setBusy] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const dirty = useRef(false);

  // секундомер карточки считается от момента принятия вызова
  useEffect(() => {
    if (phase !== "card" || startedAt == null) return;
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 500);
    return () => clearInterval(id);
  }, [phase, startedAt]);

  // автосохранение черновика: ответ не теряется при обрыве связи
  useEffect(() => {
    if (phase !== "card" || !card) return;
    const id = setInterval(() => {
      if (!dirty.current) return;
      dirty.current = false;
      api.put(`/attempts/${card.attempt.id}/draft`, { answer, actions }).catch(() => { dirty.current = true; });
    }, 6000);
    return () => clearInterval(id);
  }, [phase, card, answer, actions]);

  const change = useCallback((key: string, value: string) => {
    dirty.current = true;
    setAnswer((a) => ({ ...a, [key]: value }));
    const type = ACTION_BY_FIELD[key];
    if (type) setActions((list) => (list.some((x) => x.type === type) ? list : [...list, { type }]));
  }, []);

  const waitCall = async () => {
    setBusy(true);
    try {
      const next = await api.post<NextCard>(`/sessions/${sessionId}/attempts/next`);
      setCard(next);
      setAnswer({}); setActions([]); setMessages([]); setResult(null); setBuffered(false); setElapsed(0);
      dirty.current = false;
      setPhase("ringing");
    } catch (e) {
      if (e instanceof ApiError && e.code === "attempt_in_progress") notify("Есть незавершённая карточка: обновите страницу через минуту или попросите преподавателя завершить занятие");
      else if (e instanceof ApiError && e.code === "session_not_running") { notify("Занятие ещё не запущено преподавателем"); session.reload(); }
      else fail(e);
    } finally { setBusy(false); }
  };

  const accept = async () => {
    if (!card) return;
    setBusy(true);
    try {
      const res = await api.post<{ messages: CallMessage[] }>(`/attempts/${card.attempt.id}/answer`);
      setMessages(res.messages ?? []);
      setStartedAt(Date.now());
      setPhase("card");
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const submit = async () => {
    if (!card) return;
    setBusy(true);
    try {
      const body = { answer, actions: [...actions, { type: "save_card" }] };
      const res = await api.post<AttemptResult & { _buffered?: boolean }>(`/attempts/${card.attempt.id}/submit`, body);
      if (res._buffered) {
        setBuffered(true);
        setResult(null);
      } else setResult(res);
      setPhase("result");
      journal.reload();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  // результат из буфера появляется позже: опрашиваем, пока карточка не будет оценена
  useEffect(() => {
    if (!buffered || !card) return;
    const id = setInterval(async () => {
      try {
        const r = await api.get<AttemptResult>(`/attempts/${card.attempt.id}`);
        setResult(r); setBuffered(false);
      } catch { /* 409 — ещё обрабатывается */ }
    }, 3000);
    return () => clearInterval(id);
  }, [buffered, card]);

  const sendMessage = async (text: string) => {
    if (!card) return;
    try {
      const res = await api.post<{ messages: CallMessage[] }>(`/attempts/${card.attempt.id}/messages`, { text });
      setMessages(res.messages);
    } catch (e) { fail(e); }
  };

  const abandon = () => {
    if (window.confirm("Сбросить вызов? Карточка останется без оценки.")) { setPhase("journal"); setCard(null); }
  };

  const running = session.data?.status === "running";
  const timer = { sec: elapsed, over: !!card && elapsed > card.time_limit_sec };

  return (
    <div className="arm">
      {phase !== "card" && (
        <header className="arm-head">
          <div><h1>Поиск происшествий</h1><small>{session.data?.title ?? "…"} · {user?.full_name}</small></div>
          <span className="spacer" />
          <Link to="/student" className="arm-exit">← в кабинет</Link>
          <Clock />
        </header>
      )}

      {phase === "journal" && (
        <Journal
          attempts={journal.data?.items ?? []}
          running={running}
          status={session.data?.status}
          busy={busy}
          onWait={waitCall}
          onOpen={(id) => nav(`/student/errors?attempt=${id}`)}
        />
      )}

      {phase === "ringing" && card && (
        <>
          <Journal attempts={journal.data?.items ?? []} running status="running" busy onWait={() => {}} onOpen={() => {}} dim />
          <Modal title="Входящий вызов" onClose={() => {}} badge={<span className="badge accent" style={{ marginLeft: 8 }}>УЧЕБНЫЙ ВЫЗОВ</span>}
            footer={<button className="btn green block" style={{ padding: 14, fontSize: 16 }} onClick={accept} disabled={busy}>Принять</button>}>
            <div style={{ textAlign: "center" }}>
              <div className="ring">☎</div>
              <div style={{ fontSize: 26, fontWeight: 500, margin: "12px 0 4px" }}>{card.call.caller_number}</div>
              <div className="muted small">АОН определён · {card.call.channel === "voip" ? "голосовой канал" : "текстовый канал"} · норматив {card.time_limit_sec} с</div>
              <div className="muted small" style={{ marginTop: 10 }}>После принятия откроется новая карточка происшествия</div>
            </div>
          </Modal>
        </>
      )}

      {phase === "card" && card && (
        <CardEditor
          card={card}
          answer={answer}
          onChange={change}
          onSave={submit}
          onCancel={abandon}
          saving={busy}
          timer={timer}
          callSlot={<Dialog card={card} messages={messages} onSend={sendMessage} />}
        />
      )}

      {phase === "result" && (
        <div className="arm-result">
          <ResultView result={result} buffered={buffered} attemptSeq={card?.attempt.seq} />
          <div className="row" style={{ justifyContent: "center", gap: 12, marginTop: 20 }}>
            <button className="btn primary" onClick={() => { setPhase("journal"); setCard(null); }}>В журнал происшествий</button>
            {running && <button className="btn dark" onClick={async () => { setPhase("journal"); await waitCall(); }}>Следующий вызов</button>}
          </div>
        </div>
      )}
    </div>
  );
}

function Journal({ attempts, running, status, busy, onWait, onOpen, dim }: {
  attempts: Attempt[]; running: boolean; status?: string; busy: boolean; onWait: () => void; onOpen: (id: string) => void; dim?: boolean;
}) {
  return (
    <div className={`arm-journal${dim ? " dim" : ""}`}>
      <div className="row" style={{ marginBottom: 12 }}>
        <h2>Список происшествий</h2>
        <span className="spacer" />
        {status === "planned" && <span className="badge blue">Занятие ещё не запущено</span>}
        {status === "finished" && <span className="badge">Занятие завершено</span>}
        <button className="btn primary" disabled={!running || busy} onClick={onWait}>Ожидать вызов</button>
      </div>
      {attempts.length === 0 ? (
        <div className="jempty">Журнал пуст. Нажмите «Ожидать вызов», чтобы получить первое происшествие.</div>
      ) : (
        <table className="jtable">
          <thead><tr><th>Карт.</th><th>Время</th><th>Статус</th><th>Оценка</th><th>Норматив</th><th /></tr></thead>
          <tbody>
            {attempts.map((a) => (
              <tr key={a.id}>
                <td><b>{a.seq}</b></td>
                <td>{shortDate(a.issued_at)}</td>
                <td><span className={`jstatus ${a.status}`}>{STATUS[a.status] ?? a.status}</span></td>
                <td>{a.final_score != null ? num(a.final_score) : "—"}</td>
                <td>{a.time_limit_sec} с</td>
                <td>{a.status === "evaluated" && <button className="jbtn" onClick={() => onOpen(a.id)}>разбор</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const STATUS: Record<string, string> = { issued: "Вызов", in_progress: "В работе", submitted: "Проверка", evaluated: "Оценена", expired: "Пропущена" };

function Dialog({ card, messages, onSend }: { card: NextCard; messages: CallMessage[]; onSend: (t: string) => void }) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages]);
  const voip = card.call.channel === "voip";
  return (
    <div className="dialog">
      <div className="arm-h">{voip ? "🎧 Голосовой вызов" : "💬 Диалог с заявителем"}</div>
      {voip && <div className="small muted" style={{ marginBottom: 6 }}>Заявитель звонит на ваш софтфон{card.call.sip_server ? ` (${card.call.sip_server})` : ""}. Заполняйте карточку по разговору; текстовый чат — резервный канал.</div>}
      <div className="msgs">
        {messages.length === 0 && <div className="muted small">Заявитель ждёт вашего вопроса…</div>}
        {messages.map((m) => <div key={m.id} className={`msg ${m.author}`}>{m.text}</div>)}
        <div ref={end} />
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onSend(text.trim()); setText(""); } }}>
        <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ваш вопрос заявителю" />
        <button className="btn dark">Отправить</button>
      </form>
    </div>
  );
}

function ResultView({ result, buffered, attemptSeq }: { result: AttemptResult | null; buffered: boolean; attemptSeq?: number }) {
  const errors = useMemo(() => result?.errors ?? [], [result]);
  if (buffered) return <div className="panel" style={{ textAlign: "center" }}><h2>Ответ принят</h2><p className="muted" style={{ marginTop: 8 }}>Сервер временно недоступен, ваш ответ сохранён в буфере. Результат появится автоматически.</p></div>;
  if (!result) return null;
  return (
    <div className="panel" style={{ maxWidth: 760, margin: "0 auto" }}>
      <div className="row" style={{ alignItems: "baseline", gap: 16 }}>
        <h2 style={{ margin: 0 }}>Карточка {attemptSeq ?? result.seq}</h2>
        <span style={{ fontSize: 40, fontWeight: 500 }}>{num(result.score)}</span><span className="muted">/ 100</span>
        <span className={`badge ${result.passed ? "green" : "red"}`}>{result.passed ? "Зачёт" : "Не зачтено"}</span>
        <span className="spacer" />
        <span className="small muted">{num((result.duration_ms ?? 0) / 1000)} с из {result.time_limit_sec} с{result.delta_sec > 0 ? ` (+${result.delta_sec})` : ""}</span>
      </div>
      {result.details_hidden && <p className="muted" style={{ marginTop: 12 }}>Идёт аттестация: разбор ошибок откроется после завершения занятия.</p>}
      {errors.length > 0 && (
        <table className="tbl" style={{ marginTop: 14 }}>
          <thead><tr><th>Поле</th><th>Тип</th><th>Замечание</th><th>Ответ</th><th>Эталон</th></tr></thead>
          <tbody>{errors.map((e, i) => (
            <tr key={i}><td>{fieldLabel(e.field_key)}</td><td><span className={`badge ${ERROR_KINDS[e.kind]?.tone ?? ""}`}>{ERROR_KINDS[e.kind]?.label ?? e.kind}</span></td><td>{e.message}</td><td>{showValue(e.actual)}</td><td>{showValue(e.expected)}</td></tr>
          ))}</tbody>
        </table>
      )}
      {!result.details_hidden && errors.length === 0 && <p style={{ marginTop: 12, color: "var(--c-green)" }}>Замечаний нет — карточка заполнена точно.</p>}
    </div>
  );
}
