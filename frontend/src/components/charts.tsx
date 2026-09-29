// Лёгкие SVG-графики в стиле макетов (без внешних библиотек).

export function LineChart({ points, labels, min = 0, max = 100, height = 200, color = "var(--c-accent)" }: {
  points: number[]; labels?: string[]; min?: number; max?: number; height?: number; color?: string;
}) {
  const W = 560, H = height, L = 34, R = 12, T = 10, B = 24;
  const n = points.length;
  const x = (i: number) => L + (n <= 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (n - 1));
  const y = (v: number) => T + (1 - (v - min) / (max - min || 1)) * (H - T - B);
  const ticks = 5;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} role="img">
      {Array.from({ length: ticks }, (_, i) => {
        const v = min + ((max - min) * i) / (ticks - 1);
        return (
          <g key={i}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#d5dadd" />
            <text x={L - 6} y={y(v) + 3} fontSize="9" fill="#6b7378" textAnchor="end">{Math.round(v)}</text>
          </g>
        );
      })}
      {n > 1 && <polyline fill="none" stroke={color} strokeWidth="2" points={points.map((p, i) => `${x(i)},${y(p)}`).join(" ")} />}
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(p)} r="3.5" fill="#fff" stroke={color} strokeWidth="2" />
          {labels?.[i] && <text x={x(i)} y={H - 6} fontSize="9" fill="#6b7378" textAnchor="middle">{labels[i]}</text>}
        </g>
      ))}
    </svg>
  );
}

const BAR_COLORS = ["#1c7cc0", "#1c7cc0", "#3e9b5f", "#f1b73f", "#1c7cc0"];

export function BarChart({ items, max = 100, height = 220 }: { items: { label: string; value: number }[]; max?: number; height?: number }) {
  const W = 560, H = height, L = 30, B = 24, T = 8;
  const bw = items.length ? (W - L - 10) / items.length : 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} role="img">
      {[0, 25, 50, 75, 100].map((t) => {
        const yy = T + (1 - t / 100) * (H - T - B);
        return <g key={t}><line x1={L} x2={W - 4} y1={yy} y2={yy} stroke="#d5dadd" /><text x={L - 5} y={yy + 3} fontSize="9" fill="#6b7378" textAnchor="end">{Math.round((t / 100) * max)}</text></g>;
      })}
      {items.map((it, i) => {
        const h = (Math.min(it.value, max) / max) * (H - T - B);
        return (
          <g key={i}>
            <rect x={L + i * bw + bw * 0.14} y={H - B - h} width={bw * 0.72} height={h} fill={BAR_COLORS[i % BAR_COLORS.length]} />
            <text x={L + i * bw + bw / 2} y={H - 8} fontSize="9" fill="#6b7378" textAnchor="middle">{it.label}</text>
          </g>
        );
      })}
    </svg>
  );
}
