"use client";

import { useEffect, useRef, useState } from "react";

interface DataPoint {
  label: string;
  value: number;
}

interface ChartProps {
  title: string;
  data: DataPoint[];
  color?: string;
  gradientId: string;
  unit?: string;
  height?: number;
  description?: string;
}

export function SVGLineChart({
  title,
  data,
  color = "#a8801f",
  gradientId,
  unit = "",
  height = 200,
  description,
}: ChartProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  // Match the viewBox to the measured width so text keeps its real size.
  const containerRef = useRef<HTMLDivElement>(null);
  const [measuredWidth, setMeasuredWidth] = useState(500);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setMeasuredWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const latest = data.length ? data[data.length - 1].value : null;

  const padX = 44;
  const padY = 16;
  const chartHeight = height - padY * 2;
  const values = data.map((d) => d.value);
  const maxValue = Math.max(...values, 1);
  const minValue = Math.min(...values, 0);
  const range = maxValue - minValue || 1;
  const width = Math.max(measuredWidth, 240);
  const chartWidth = width - padX - 12;

  const points = data.map((d, idx) => {
    const x = padX + (data.length === 1 ? chartWidth / 2 : (idx / (data.length - 1)) * chartWidth);
    const y = padY + chartHeight - ((d.value - minValue) / range) * chartHeight;
    return { x, y, ...d };
  });
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const areaPath = points.length
    ? `${linePath} L ${points[points.length - 1].x} ${height - padY} L ${points[0].x} ${height - padY} Z`
    : "";
  const hovered = hoveredIdx !== null ? points[hoveredIdx] : null;

  return (
    <div className="card flex flex-col p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
        </div>
        {latest !== null && (
          <span className="shrink-0 text-lg font-semibold tabular-nums text-foreground">
            {latest.toFixed(1)}
            <span className="ml-0.5 text-xs font-medium text-muted-foreground">{unit}</span>
          </span>
        )}
      </div>

      {data.length === 0 ? (
        <div className="flex flex-1 items-center justify-center py-12 text-sm text-muted-foreground">No data yet</div>
      ) : (
        <>
          <div ref={containerRef} className="relative" style={{ height }}>
            <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full overflow-visible" role="img" aria-label={`${title} chart`}>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity="0.18" />
                  <stop offset="100%" stopColor={color} stopOpacity="0" />
                </linearGradient>
              </defs>
              {[0, 0.5, 1].map((f) => {
                const y = padY + chartHeight * f;
                const v = maxValue - range * f;
                return (
                  <g key={f}>
                    <line x1={padX} y1={y} x2={width - 12} y2={y} stroke="#e3ddd3" strokeDasharray={f === 1 ? undefined : "3 4"} />
                    <text x={padX - 8} y={y + 3.5} fill="#66625c" fontSize="10" textAnchor="end">
                      {v.toFixed(v < 10 ? 1 : 0)}
                      {unit}
                    </text>
                  </g>
                );
              })}
              {areaPath && <path d={areaPath} fill={`url(#${gradientId})`} />}
              {linePath && <path d={linePath} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />}
              {hovered && <line x1={hovered.x} y1={padY} x2={hovered.x} y2={height - padY} stroke="#cdc4b6" />}
              {points.map((p, idx) => (
                <g key={idx} onMouseEnter={() => setHoveredIdx(idx)} onMouseLeave={() => setHoveredIdx(null)}>
                  <rect x={p.x - chartWidth / Math.max(points.length, 1) / 2} y={padY} width={chartWidth / Math.max(points.length, 1)} height={chartHeight} fill="transparent" />
                  <circle cx={p.x} cy={p.y} r={hoveredIdx === idx ? 4.5 : points.length > 40 ? 0 : 2.5} fill="#fff" stroke={color} strokeWidth="2" />
                </g>
              ))}
            </svg>
            {hovered && (
              <div
                className="pointer-events-none absolute -translate-x-1/2 -translate-y-full rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs shadow-[var(--shadow-md)]"
                style={{ left: `${(hovered.x / width) * 100}%`, top: hovered.y - 8 }}
              >
                <span className="font-semibold tabular-nums">{hovered.value.toFixed(1)}{unit}</span>
                <span className="ml-1.5 text-muted-foreground">{hovered.label}</span>
              </div>
            )}
          </div>
          <div className="mt-2 flex justify-between text-[11px] text-muted-foreground" style={{ paddingLeft: padX }}>
            <span>{data[0]?.label}</span>
            {data.length > 2 && <span>{data[Math.floor(data.length / 2)]?.label}</span>}
            <span>{data[data.length - 1]?.label}</span>
          </div>
        </>
      )}
    </div>
  );
}
