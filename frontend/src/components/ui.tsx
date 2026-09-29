import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export const Badge = ({ tone, children }: { tone?: "green" | "red" | "yellow" | "blue" | "accent"; children: ReactNode }) => (
  <span className={`badge${tone ? " " + tone : ""}`}>{children}</span>
);

export const Stat = ({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "blue" | "green" | "red" }) => (
  <div className="stat">
    <div className="k">{label}</div>
    <div className="v">{value}</div>
    {sub != null && <div className={`sub ${tone ?? "blue"}`}>{sub}</div>}
  </div>
);

export const Panel = ({ title, aside, children, className = "", style }: { title?: string; aside?: ReactNode; children: ReactNode; className?: string; style?: React.CSSProperties }) => (
  <section className={`panel ${className}`} style={style}>
    {(title || aside) && (
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 className="panel-title" style={{ margin: 0 }}>{title}</h2>
        <span className="spacer" />
        {aside}
      </div>
    )}
    {children}
  </section>
);

export const Bar = ({ value, tone = "blue" }: { value: number; tone?: "blue" | "green" | "red" | "yellow" | "accent" }) => (
  <div className={`bar ${tone}`}><i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>
);

export const Loading = () => <div className="empty">Загрузка…</div>;

export function ErrorBox({ error, retry }: { error: Error; retry?: () => void }) {
  const text = error instanceof ApiError && error.status === 403 ? "Недостаточно прав для просмотра" : error.message;
  return (
    <div className="empty">
      <div className="err-text" style={{ fontSize: 13 }}>{text}</div>
      {retry && <button className="btn sm" style={{ marginTop: 12 }} onClick={retry}>Повторить</button>}
    </div>
  );
}

export function Modal({ title, onClose, children, footer, badge }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; badge?: ReactNode }) {
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">
        <header><span>{title}</span>{badge}<span className="spacer" /><button className="btn sm" style={{ background: "transparent", color: "#fff", border: 0 }} onClick={onClose} aria-label="Закрыть">✕</button></header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <label className="field"><span>{label}</span>{children}</label>
);

export const statusTone = (s: string): "green" | "red" | "yellow" | "blue" | undefined =>
  ({ running: "green", evaluated: "green", validated: "green", planned: "blue", in_progress: "blue", pending_review: "yellow", draft: undefined, finished: undefined, expired: "red", rejected: "red" } as const)[s as "running"];
