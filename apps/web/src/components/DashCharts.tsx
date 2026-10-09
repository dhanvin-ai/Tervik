// Line chart for the overview hero: thin line, hollow point markers, plain gridlines.
import { useState } from 'react';

type Day = { date: string; conversations: number; failures: number };

const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

/** Rounds a rough step up to 1, 2, 2.5, or 5 times a power of ten. */
function niceStep(rough: number) {
  const power = 10 ** Math.floor(Math.log10(Math.max(rough, 1e-9)));
  const scaled = rough / power;
  return (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10) * power;
}

/** Daily problem rate. Days without conversations have no rate, so they get no point. */
export function RateChart({ trend, summary }: { trend: Day[]; summary: string }) {
  const [active, setActive] = useState<number | null>(null);
  const width = 520, height = 230, left = 44, right = 20, top = 12, bottom = 30;
  const points = trend.flatMap((day, index) => day.conversations ? [{ index, date: day.date, rate: (100 * day.failures) / day.conversations }] : []);
  const step = Math.min(50, niceStep(Math.max(...points.map(point => point.rate), 10) / 3));
  const maximum = Math.min(100, Math.ceil(Math.max(...points.map(point => point.rate), step) / step) * step);
  const ticks = Array.from({ length: Math.round(maximum / step) + 1 }, (_, i) => i * step);
  const band = (width - left - right) / Math.max(1, trend.length - 1);
  const x = (index: number) => left + index * band;
  const y = (rate: number) => top + (1 - rate / maximum) * (height - top - bottom);
  const line = points.map((point, i) => `${i ? 'L' : 'M'}${x(point.index).toFixed(1)},${y(point.rate).toFixed(1)}`).join(' ');
  const labelEvery = Math.max(1, Math.ceil(trend.length / 5));
  const labels = trend.map((day, index) => ({ index, date: day.date }))
    .filter(({ index }) => index % labelEvery === 0 || (index === trend.length - 1 && index % labelEvery >= labelEvery / 2));
  const hovered = active !== null ? points.find(point => point.index === active) : undefined;
  return (
    <figure className="dash-rate" onMouseLeave={() => setActive(null)}>
      <figcaption className="dash-rate-title">{summary}</figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={points.length ? `Daily problem rate, from ${points[0].rate.toFixed(0)} to ${points[points.length - 1].rate.toFixed(0)} percent` : 'No daily data yet'}>
        {ticks.map(tick => <g key={tick}>
          <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="dash-rate-grid" />
          <text x={4} y={y(tick) + 4} className="dash-rate-axis">{Number.isInteger(tick) ? tick : tick.toFixed(1)}%</text>
        </g>)}
        {labels.map(({ index, date }) => <text key={date} x={x(index)} y={height - 6} textAnchor="middle" className="dash-rate-axis">{shortDate(date)}</text>)}
        {points.length > 0 && <path d={line} className="dash-rate-line" />}
        {points.map(point => <circle key={point.date} cx={x(point.index)} cy={y(point.rate)} r={active === point.index ? 5 : 3.5} className="dash-rate-point" />)}
        {trend.map((day, index) => <rect key={day.date} x={x(index) - band / 2} y={top} width={band} height={height - top - bottom} fill="transparent" onMouseEnter={() => setActive(index)} />)}
        {hovered && (() => {
          const label = `${shortDate(hovered.date)} · ${hovered.rate.toFixed(0)}%`;
          const boxWidth = label.length * 7 + 16;
          const boxX = Math.min(Math.max(x(hovered.index) - boxWidth / 2, left), width - right - boxWidth);
          const boxY = Math.max(y(hovered.rate) - 34, 0);
          return <g className="dash-rate-tip" pointerEvents="none">
            <rect x={boxX} y={boxY} width={boxWidth} height={22} rx={3} />
            <text x={boxX + boxWidth / 2} y={boxY + 15} textAnchor="middle">{label}</text>
          </g>;
        })()}
      </svg>
    </figure>
  );
}
