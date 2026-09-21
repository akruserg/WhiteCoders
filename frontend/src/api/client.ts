// Тонкий клиент к REST API: Bearer-токен, автоматическое обновление по refresh,
// единый формат ошибок {"error": {code, message, details}, request_id}.

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";
const ACCESS_KEY = "arm112.access";
const REFRESH_KEY = "arm112.refresh";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  requestId?: string;
  retryAfter?: number;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export const tokens = {
  get access() { return sessionStorage.getItem(ACCESS_KEY); },
  get refresh() { return sessionStorage.getItem(REFRESH_KEY); },
  set(access: string, refresh: string) {
    sessionStorage.setItem(ACCESS_KEY, access);
    sessionStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    sessionStorage.removeItem(ACCESS_KEY);
    sessionStorage.removeItem(REFRESH_KEY);
  },
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  // параллельные запросы ждут одну и ту же ротацию: refresh-токен одноразовый
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      tokens.set(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      setTimeout(() => { refreshing = null; }, 0);
    }
  })();
  return refreshing;
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: string;
  query?: Query;
  body?: unknown;
  form?: FormData;
  auth?: boolean;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: Query) {
  const url = `${BASE}${path}`;
  if (!query) return url;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${url}?${s}` : url;
}

async function raw(path: string, opts: RequestOptions, retry = true): Promise<Response> {
  const headers: Record<string, string> = {};
  if (opts.auth !== false && tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }

  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", "Нет связи с сервером");
  }

  if (res.status === 401 && opts.auth !== false && retry && tokens.refresh) {
    if (await refreshTokens()) return raw(path, opts, false);
    tokens.clear();
    onUnauthorized();
  }
  return res;
}

async function toError(res: Response): Promise<ApiError> {
  let payload: any = null;
  try { payload = await res.json(); } catch { /* тело не JSON */ }
  const err = payload?.error;
  const e = new ApiError(
    res.status,
    err?.code ?? "error",
    err?.message ?? `Ошибка ${res.status}`,
    err?.details ?? {},
    payload?.request_id,
  );
  const ra = res.headers.get("Retry-After");
  if (ra) e.retryAfter = Number(ra);
  return e;
}

export async function request<T = any>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await raw(path, opts);
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("Content-Type") ?? "";
  if (!ct.includes("json")) return (await res.text()) as unknown as T;
  const data = await res.json();
  // 202: сервер принял данные в буфер (сбой БД), результат появится позже
  if (res.status === 202 && data && typeof data === "object") (data as any)._buffered = true;
  return data as T;
}

export async function download(path: string, filename: string, query?: Query) {
  const res = await raw(path, { query });
  if (!res.ok) throw await toError(res);
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : filename;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export const api = {
  get: <T = any>(path: string, query?: Query, signal?: AbortSignal) => request<T>(path, { query, signal }),
  post: <T = any>(path: string, body?: unknown, query?: Query) => request<T>(path, { method: "POST", body: body ?? {}, query }),
  put: <T = any>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body: body ?? {} }),
  patch: <T = any>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body: body ?? {} }),
  del: <T = any>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T = any>(path: string, form: FormData, query?: Query) => request<T>(path, { method: "POST", form, query }),
  anon: <T = any>(path: string, body: unknown) => request<T>(path, { method: "POST", body, auth: false }),
};
