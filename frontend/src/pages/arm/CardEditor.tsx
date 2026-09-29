import { useMemo, useState } from "react";
import type { Category, Listed, NextCard, TemplateField } from "../../api/types";
import { api } from "../../api/client";
import { Modal } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { ADDRESS_KEYS, PHONE_KEYS, QUICK_TYPES, QUICK_VICTIMS, SERVICES } from "./constants";

export type Answer = Record<string, string>;

interface Props {
  card: NextCard;
  answer: Answer;
  onChange: (key: string, value: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  timer: { sec: number; over: boolean };
  callSlot: React.ReactNode;
}

export default function CardEditor({ card, answer, onChange, onSave, onCancel, saving, timer, callSlot }: Props) {
  const fields = card.template_fields;
  const byKey = useMemo(() => Object.fromEntries(fields.map((f) => [f.key, f])) as Record<string, TemplateField>, [fields]);
  const has = (k: string) => k in byKey;
  const val = (k: string) => answer[k] ?? "";
  const services = val("services") ? val("services").split(", ").filter(Boolean) : [];
  const [pickServices, setPickServices] = useState(false);
  const extra = fields.filter((f) => ![...PHONE_KEYS, ...ADDRESS_KEYS, "applicant_name", "incident_type", "incident_details", "victims", "services", "description"].includes(f.key));

  const cats = useLoad(() => api.get<Listed<Category>>("/categories"));
  const types = useMemo(() => {
    const all = cats.data?.items ?? [];
    const rootIds = new Set(all.filter((c) => c.parent_id == null).map((c) => c.id));
    return all.filter((c) => c.parent_id != null && !rootIds.has(c.id)).map((c) => c.name);
  }, [cats.data]);

  const toggleService = (s: string) => {
    const next = services.includes(s) ? services.filter((x) => x !== s) : [...services, s];
    onChange("services", next.join(", "));
  };

  const mm = String(Math.floor(timer.sec / 60)).padStart(2, "0");
  const ss = String(timer.sec % 60).padStart(2, "0");
  const label = (k: string) => byKey[k]?.label ?? k;

  return (
    <div className="arm-card">
      <div className="arm-top">
        <div className="arm-hangup"><button onClick={onCancel} title="Сбросить вызов (карточка не будет отправлена)">☎</button><span>Вызов</span></div>
        {PHONE_KEYS.map((k, i) => has(k) || i === 0 ? (
          <div key={k} className="arm-phone">
            <small>{k === "phone_aon" ? "АОН" : k === "phone_provided" ? "предоставленный" : "телефон на место"}</small>
            <input value={val(k)} placeholder="+7 ( ) - -" onChange={(e) => onChange(k, e.target.value)} />
          </div>
        ) : null)}
        <div className="arm-incident"><b>Происшествие {card.attempt.id.slice(0, 8)}</b><small>Карточка {card.attempt.seq} · {card.call.caller_number}</small></div>
        <div className={`arm-timer${timer.over ? " over" : ""}`}><span>{mm}:{ss}</span><small>норматив {card.time_limit_sec} с</small></div>
      </div>

      <div className="arm-body">
        <div className="arm-col">
          {has("applicant_name") && (
            <div className="arm-box"><label className="afield"><small>{label("applicant_name")}</small><input value={val("applicant_name")} onChange={(e) => onChange("applicant_name", e.target.value)} /></label></div>
          )}
          <div className="arm-box grow">
            <div className="arm-h">📍 Адрес</div>
            <div className="addr">
              {ADDRESS_KEYS.filter(has).map((k) => (
                <label key={k} className={`afield${k === "address_street" ? " wide" : ""}`}><small>{label(k)}{byKey[k].required ? " *" : ""}</small>
                  <input value={val(k)} onChange={(e) => onChange(k, e.target.value)} /></label>
              ))}
            </div>
          </div>
          <div className="arm-box">
            {callSlot}
          </div>
        </div>

        <div className="arm-col">
          <div className="arm-box">
            <div className="quick">
              {has("victims") && QUICK_VICTIMS.map((v) => (
                <button key={v} className={`chip${val("victims") === v ? " on" : ""}`} onClick={() => onChange("victims", v)}>Пострадавшие: {v.toLowerCase()}</button>
              ))}
            </div>
            {has("victims") && <label className="afield" style={{ marginTop: 8 }}><small>{label("victims")}{byKey.victims.required ? " *" : ""}</small><input value={val("victims")} onChange={(e) => onChange("victims", e.target.value)} /></label>}
          </div>

          <div className="arm-box grow">
            {has("incident_type") && (
              <>
                <label className="afield"><small>{label("incident_type")} *</small>
                  <input list="incident-types" className="big" placeholder="что случилось?" value={val("incident_type")} onChange={(e) => onChange("incident_type", e.target.value)} />
                </label>
                <datalist id="incident-types">{types.map((t) => <option key={t} value={t} />)}</datalist>
                <div className="quick" style={{ marginTop: 10 }}>
                  {QUICK_TYPES.map((t) => <button key={t} className="chip" onClick={() => onChange("incident_type", t.toLowerCase())}>{t}</button>)}
                </div>
              </>
            )}
            {has("incident_details") && (
              <label className="afield" style={{ marginTop: 14 }}><small>{label("incident_details")} *</small>
                <textarea rows={4} value={val("incident_details")} onChange={(e) => onChange("incident_details", e.target.value)} /></label>
            )}
            {extra.map((f) => (
              <label key={f.key} className="afield" style={{ marginTop: 10 }}><small>{f.label}{f.required ? " *" : ""}</small>
                {f.type === "textarea" ? <textarea rows={3} value={val(f.key)} onChange={(e) => onChange(f.key, e.target.value)} /> : <input value={val(f.key)} onChange={(e) => onChange(f.key, e.target.value)} />}
              </label>
            ))}
          </div>
        </div>
      </div>

      {has("description") && (
        <div className="arm-desc"><label className="afield"><small>{label("description")} *</small>
          <textarea rows={3} maxLength={1999} value={val("description")} onChange={(e) => onChange("description", e.target.value)} placeholder="введите" />
          <small style={{ textAlign: "right" }}>{val("description").length} / 1999</small></label></div>
      )}

      <div className="arm-services">
        <span>Службы:</span>
        <button className="plus" onClick={() => setPickServices(true)} title="Добавить службы">+</button>
        <div className="svc-list">{services.map((s) => <button key={s} className="svc" onClick={() => toggleService(s)} title="Убрать">{s} ✕</button>)}</div>
        <span className="spacer" />
        <button className="save" onClick={onSave} disabled={saving}>{saving ? "отправка…" : "сохранить"}</button>
      </div>

      {pickServices && (
        <Modal title="Добавление служб" onClose={() => setPickServices(false)} footer={<button className="btn primary" onClick={() => setPickServices(false)}>Готово</button>}>
          <div className="quick">
            {SERVICES.map((s) => <button key={s} className={`chip${services.includes(s) ? " on" : ""}`} onClick={() => toggleService(s)}>{s}</button>)}
          </div>
        </Modal>
      )}
    </div>
  );
}
