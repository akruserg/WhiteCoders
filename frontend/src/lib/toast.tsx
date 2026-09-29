import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";

interface T { id: number; text: string; error?: boolean }
const Ctx = createContext<{ notify: (text: string) => void; fail: (e: unknown) => void }>({ notify() {}, fail() {} });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<T[]>([]);
  const push = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setItems((s) => [...s, { id, text, error }]);
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), error ? 6000 : 3500);
  }, []);
  const notify = useCallback((t: string) => push(t), [push]);
  const fail = useCallback((e: unknown) => {
    push(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Неизвестная ошибка", true);
  }, [push]);
  return (
    <Ctx.Provider value={{ notify, fail }}>
      {children}
      <div className="toast-root">{items.map((t) => <div key={t.id} className={`toast${t.error ? " error" : ""}`}>{t.text}</div>)}</div>
    </Ctx.Provider>
  );
}
export const useToast = () => useContext(Ctx);
