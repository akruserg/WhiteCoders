import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth, homePath } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import type { MfaChallenge } from "../api/types";

export default function Login() {
  const { user, login, verifyMfa } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState<MfaChallenge | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={homePath(user.role.code)} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mfa) await verifyMfa(mfa.mfa_token, code.trim());
      else setMfa(await login(username.trim(), password));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось выполнить вход");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="login-form" onSubmit={submit}>
        <div className="login-title"><span>112</span><b>ВХОД В СИСТЕМУ</b></div>
        {!mfa ? (
          <>
            <label><small>логин</small>
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
            </label>
            <label><small>пароль</small>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
          </>
        ) : (
          <label><small>код подтверждения (второй фактор)</small>
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={8} autoFocus required />
          </label>
        )}
        {error && <div className="login-err">{error}</div>}
        <button className="login-btn" disabled={busy}>{busy ? "ПОДОЖДИТЕ…" : mfa ? "ПОДТВЕРДИТЬ" : "ВОЙТИ"}</button>
        <div className="login-help">
          Техподдержка<br />+7 (495) 197-89-81<br />(многоканальный)<br />
          <a href="mailto:hd-112@mos.ru">hd-112@mos.ru</a>
        </div>
      </form>
    </div>
  );
}
