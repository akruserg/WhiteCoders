const MONTHS = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
const DAYS = ["Воскресенье","Понедельник","Вторник","Среда","Четверг","Пятница","Суббота"];

export const pad = (n: number) => String(n).padStart(2, "0");
export const mmss = (sec: number) => `${pad(Math.floor(Math.abs(sec) / 60))}:${pad(Math.abs(sec) % 60)}`;
export const fullDate = (d = new Date()) => `${DAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
export const shortDate = (iso?: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const dayMonth = (iso: string) => { const d = new Date(iso); return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}`; };
export const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((s) => s[0]?.toUpperCase()).join("");
export const num = (v: number | null | undefined, digits = 0) => (v == null ? "—" : Number(v).toFixed(digits).replace(/\.0+$/, ""));

export const DIFFICULTY = ["", "Лёгкий", "Средний", "Сложный", "Очень сложный", "Эксперт"];
export const difficultyTone = (d: number) => (d <= 1 ? "green" : d === 2 ? "yellow" : "red");
export const ROLE_NAME: Record<string, string> = { admin: "Администратор", teacher: "Преподаватель", student: "Обучающийся" };

export const FIELD_LABELS: Record<string, string> = {
  phone_aon: "Телефон АОН", phone_provided: "Предоставленный номер", phone_place: "Телефон на место",
  applicant_name: "Заявитель", incident_type: "Тип происшествия", incident_details: "Подробности",
  address_street: "Улица", address_house: "Дом", address_flat: "Квартира/офис", address_entrance: "Подъезд",
  address_floor: "Этаж", victims: "Пострадавшие", services: "Службы", description: "Описание",
};
export const fieldLabel = (k?: string | null) => (k ? FIELD_LABELS[k] ?? k : "—");

export const ERROR_KINDS: Record<string, { label: string; tone: "red" | "yellow" | "blue" | "accent" }> = {
  content: { label: "Неверно", tone: "yellow" },
  missing: { label: "Пропущено", tone: "red" },
  grammar: { label: "Грамматика", tone: "accent" },
  timing: { label: "Просрочка", tone: "red" },
  procedure: { label: "Порядок", tone: "blue" },
};
export const showValue = (v: unknown) => (v == null || v === "" ? "—" : Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v));
