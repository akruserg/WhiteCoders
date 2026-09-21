import { useState } from "react";
import { api, download } from "../../api/client";
import { Badge, ErrorBox, Loading, Panel } from "../../components/ui";
import { useLoad } from "../../lib/hooks";
import { useToast } from "../../lib/toast";

interface Setting { key: string; scope: string; value: any; default_value: any; description: string; is_secret: boolean; requires_restart: boolean }
const SCOPE: Record<string, string> = { voip: "Телефония (VoIP)", ai: "ИИ-модуль", backup: "Резервное копирование", logging: "Журналы и оповещения", performance: "Производительность", security: "Безопасность" };

export default function Settings() {
  const { fail, notify } = useToast();
  const list = useLoad(() => api.get<{ items: Setting[] }>("/system/settings"));
  const voip = useLoad(() => api.get("/system/voip").catch(() => null));
  const [draft, setDraft] = useState<Record<string, string>>({});

  if (list.loading) return <Loading />;
  if (list.error) return <ErrorBox error={list.error} retry={list.reload} />;

  const scopes = [...new Set(list.data!.items.map((s) => s.scope))];
  const save = async (s: Setting) => {
    const raw = draft[s.key];
    let value: any = raw;
    if (typeof s.default_value === "number") value = Number(raw);
    try { await api.put(`/system/settings/${s.key}`, { value }); notify(s.requires_restart ? "Сохранено, применится после перезапуска узла" : "Настройка сохранена"); setDraft(({ [s.key]: _, ...rest }) => rest); list.reload(); }
    catch (e) { fail(e); }
  };
  const flip = async (s: Setting) => { try { await api.put(`/system/settings/${s.key}`, { value: !s.value }); list.reload(); } catch (e) { fail(e); } };
  const testNotify = async () => { try { const r = await api.post("/system/notify/test"); notify(r.configured ? "Тестовое оповещение отправлено" : "Каналы оповещения не настроены"); } catch (e) { fail(e); } };

  return (
    <div className="stack">
      <div className="row">
        {voip.data && <Badge tone={voip.data.status === "up" ? "green" : "yellow"}>SIP: {voip.data.status ?? "—"}</Badge>}
        <span className="spacer" />
        <button className="btn sm" onClick={testNotify}>Проверить оповещения</button>
        <button className="btn sm" onClick={() => download("/system/settings/export.xml", "settings.xml").catch(fail)}>Экспорт XML</button>
      </div>
      {scopes.map((scope) => (
        <Panel key={scope} title={SCOPE[scope] ?? scope}>
          <div className="stack" style={{ gap: 10 }}>
            {list.data!.items.filter((s) => s.scope === scope).map((s) => (
              <div key={s.key} className="row" style={{ background: "#fff", padding: "10px 14px", gap: 16 }}>
                <div style={{ flex: 1, minWidth: 0 }}><b style={{ fontSize: 13 }}>{s.key}</b>{s.requires_restart && <> <Badge tone="yellow">перезапуск</Badge></>}<div className="small muted">{s.description}</div></div>
                {typeof s.value === "boolean" ? (
                  <button className={`btn sm ${s.value ? "green" : ""}`} onClick={() => flip(s)}>{s.value ? "Включено" : "Выключено"}</button>
                ) : (
                  <>
                    <input className="input" style={{ width: 240 }} type={s.is_secret ? "password" : "text"} value={draft[s.key] ?? String(s.value ?? "")} onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })} />
                    <button className="btn sm primary" disabled={draft[s.key] === undefined} onClick={() => save(s)}>Сохранить</button>
                  </>
                )}
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </div>
  );
}
