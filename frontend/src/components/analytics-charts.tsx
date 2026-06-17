"use client";

import { useState } from "react";

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
}

export function SVGLineChart({
  title,
  data,
  color = "#6366f1",
  gradientId,
  unit = "",
  height = 200
}: ChartProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  if (data.length === 0) return null;

  const padding = 40;
  const chartHeight = height - padding * 2;
  
  // Calculate bounds
  const values = data.map((d) => d.value);
  const maxValue = Math.max(...values, 10);
  const minValue = Math.min(...values, 0);
  const range = maxValue - minValue;

  const width = 500;
  const chartWidth = width - padding * 2;

  // Generate coordinates
  const points = data.map((d, idx) => {
    const x = padding + (idx / (data.length - 1)) * chartWidth;
    const y = padding + chartHeight - ((d.value - minValue) / range) * chartHeight;
    return { x, y, ...d };
  });

  // SVG Line path
  const linePath = points.reduce((path, p, idx) => {
    return idx === 0 ? `M ${p.x} ${p.y}` : `${path} L ${p.x} ${p.y}`;
  }, "");

  // SVG Area path for gradient fill underneath
  const areaPath = points.length > 0 
    ? `${linePath} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`
    : "";

  return (
    <div className="glass p-6 rounded-3xl border border-card-border flex flex-col justify-between h-[300px]">
      <div>
        <h4 className="text-sm font-bold text-foreground mb-4">{title}</h4>
      </div>

      <div className="relative flex-1">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full overflow-visible">
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.3" />
              <stop offset="100%" stopColor={color} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          <line
            x1={padding}
            y1={padding}
            x2={width - padding}
            y2={padding}
            stroke="#1f2937"
            strokeDasharray="4"
          />
          <line
            x1={padding}
            y1={padding + chartHeight / 2}
            x2={width - padding}
            y2={padding + chartHeight / 2}
            stroke="#1f2937"
            strokeDasharray="4"
          />
          <line
            x1={padding}
            y1={height - padding}
            x2={width - padding}
            y2={height - padding}
            stroke="#1f2937"
          />

          {/* Y Axis Labels */}
          <text x={padding - 10} y={padding + 4} fill="#9ca3af" fontSize="10" textAnchor="end">
            {maxValue.toFixed(0)}
            {unit}
          </text>
          <text x={padding - 10} y={padding + chartHeight / 2 + 4} fill="#9ca3af" fontSize="10" textAnchor="end">
            {((maxValue + minValue) / 2).toFixed(0)}
            {unit}
          </text>
          <text x={padding - 10} y={height - padding + 4} fill="#9ca3af" fontSize="10" textAnchor="end">
            {minValue.toFixed(0)}
            {unit}
          </text>

          {/* Area fill */}
          {areaPath && <path d={areaPath} fill={`url(#${gradientId})`} />}

          {/* Line stroke */}
          {linePath && (
            <path
              d={linePath}
              fill="none"
              stroke={color}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Interactive Coordinate points */}
          {points.map((p, idx) => (
            <g
              key={idx}
              onMouseEnter={() => setHoveredIdx(idx)}
              onMouseLeave={() => setHoveredIdx(null)}
              className="cursor-pointer"
            >
              <circle
                cx={p.x}
                cy={p.y}
                r={hoveredIdx === idx ? 6 : 4}
                fill={hoveredIdx === idx ? "#white" : color}
                stroke="white"
                strokeWidth="1.5"
                className="transition-all duration-200"
              />
              
              {/* Highlight coordinates labels */}
              {hoveredIdx === idx && (
                <g>
                  {/* Tooltip background */}
                  <rect
                    x={p.x - 35}
                    y={p.y - 32}
                    width="70"
                    height="20"
                    rx="6"
                    fill="#111827"
                    stroke="#1f2937"
                    strokeWidth="1"
                  />
                  <text
                    x={p.x}
                    y={p.y - 18}
                    fill="white"
                    fontSize="9"
                    fontWeight="bold"
                    textAnchor="middle"
                  >
                    {p.value.toFixed(1)}
                    {unit}
                  </text>
                </g>
              )}
            </g>
          ))}
        </svg>
      </div>

      {/* X Axis Labels */}
      <div className="flex justify-between text-[10px] text-text-muted mt-2 px-1">
        <span>{data[0]?.label}</span>
        <span>{data[Math.floor(data.length / 2)]?.label}</span>
        <span>{data[data.length - 1]?.label}</span>
      </div>
    </div>
  );
}
