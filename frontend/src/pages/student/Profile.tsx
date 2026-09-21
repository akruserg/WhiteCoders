import { useState, type FormEvent } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { Field, Panel } from "../../components/ui";
import { ROLE_NAME, shortDate } from "../../lib/format";
import { useToast } from "../../lib/toast";

export default function Profile() {
  const { user } = useAuth();
  const { notify, fail } = useToast();
  const [oldP, setOldP] = useState("");
  const [newP, setNewP] = useState("");
  if (!user) return null;

  const change = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/auth/password", { old_password: oldP, new_password: newP });
      notify("Пароль изменён, войдите заново");
      setOldP(""); setNewP("");
    } catch (err) { fail(err); }
  };

  return (
    <div className="grid-2e">
      <Panel title="Учётная запись">
        <dl className="kv">
          <dt>ФИО</dt><dd>{user.full_name}</dd>
          <dt>Логин</dt><dd>{user.username}</dd>
          <dt>Роль</dt><dd>{ROLE_NAME[user.role.code]}</dd>
          <dt>Почта</dt><dd>{user.email ?? "—"}</dd>
          <dt>Группы</dt><dd>{user.groups.map((g) => g.name).join(", ") || "—"}</dd>
          <dt>Последний вход</dt><dd>{shortDate(user.last_login_at)}</dd>
          <dt>Согласие на обработку ПДн</dt><dd>{shortDate(user.pd_consent_at)}</dd>
          <dt>Двухфакторная защита</dt><dd>{user.mfa_enabled ? "включена" : "выключена"}</dd>
        </dl>
      </Panel>
      <Panel title="Смена пароля">
        <form className="stack" style={{ gap: 12 }} onSubmit={change}>
          <Field label="Текущий пароль"><input className="input" type="password" value={oldP} onChange={(e) => setOldP(e.target.value)} required autoComplete="current-password" /></Field>
          <Field label="Новый пароль (не менее 10 символов)"><input className="input" type="password" value={newP} onChange={(e) => setNewP(e.target.value)} required minLength={10} autoComplete="new-password" /></Field>
          <button className="btn primary" style={{ alignSelf: "flex-start" }}>Сменить пароль</button>
        </form>
      </Panel>
    </div>
  );
}
