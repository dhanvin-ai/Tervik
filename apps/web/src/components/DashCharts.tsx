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

/** Daily problem rate across every day of the range. A day without conversations
 * has no rate: it sits on the baseline as a faint point joined by a dashed line,
 * so the line spans the whole range without passing those days off as 0%. */
export function RateChart({ trend, summary }: { trend: Day[]; summary: string }) {
  const [active, setActive] = useState<number | null>(null);
  const width = 520, height = 230, left = 44, right = 20, top = 12, bottom = 30;
  const days = trend.map((day, index) => ({ ...day, index, rate: day.conversations ? (100 * day.failures) / day.conversations : null }));
  const rates = days.flatMap(day => day.rate === null ? [] : [day.rate]);
  const step = Math.min(50, niceStep(Math.max(...rates, 10) / 3));
  const maximum = Math.min(100, Math.ceil(Math.max(...rates, step) / step) * step);
  const ticks = Array.from({ length: Math.round(maximum / step) + 1 }, (_, i) => i * step);
  const band = (width - left - right) / Math.max(1, days.length - 1);
  const x = (index: number) => left + index * band;
  const y = (rate: number | null) => top + (1 - (rate ?? 0) / maximum) * (height - top - bottom);
  // Labels spread evenly from the first day to the last; at most eight fit.
  const stride = Math.max(1, Math.ceil((days.length - 1) / 7));
  const labelled: number[] = [];
  for (let index = 0; index < days.length; index += stride) labelled.push(index);
  const last = days.length - 1;
  if (last > 0 && labelled[labelled.length - 1] !== last) {
    if (last - labelled[labelled.length - 1] < stride / 2) labelled[labelled.length - 1] = last;
    else labelled.push(last);
  }
  const hovered = active !== null ? days[active] : undefined;
  return (
    <figure className="dash-rate" onMouseLeave={() => setActive(null)}>
      <figcaption className="dash-rate-title">{summary}</figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={rates.length ? `Daily problem rate over ${days.length} days, from ${rates[0].toFixed(0)} to ${rates[rates.length - 1].toFixed(0)} percent` : 'No conversations in this period'}>
        {ticks.map(tick => <g key={tick}>
          <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="dash-rate-grid" />
          <text x={4} y={y(tick) + 4} className="dash-rate-axis">{Number.isInteger(tick) ? tick : tick.toFixed(1)}%</text>
        </g>)}
        {labelled.map(index => <text key={days[index].date} x={x(index)} y={height - 6} textAnchor="middle" className="dash-rate-axis">{shortDate(days[index].date)}</text>)}
        {days.slice(1).map((day, i) => {
          const previous = days[i];
          const measured = previous.rate !== null && day.rate !== null;
          return <path key={day.date} d={`M${x(previous.index).toFixed(1)},${y(previous.rate).toFixed(1)} L${x(day.index).toFixed(1)},${y(day.rate).toFixed(1)}`}
            className={measured ? 'dash-rate-line' : 'dash-rate-gap'} />;
        })}
        {days.map(day => day.rate === null
          ? <circle key={day.date} cx={x(day.index)} cy={y(null)} r={active === day.index ? 3.5 : 2.2} className="dash-rate-empty" />
          : <circle key={day.date} cx={x(day.index)} cy={y(day.rate)} r={active === day.index ? 5 : 3.5} className="dash-rate-point" />)}
        {days.map(day => <rect key={day.date} x={x(day.index) - band / 2} y={top} width={band} height={height - top - bottom} fill="transparent" onMouseEnter={() => setActive(day.index)} />)}
        {hovered && (() => {
          const label = hovered.rate === null
            ? `${shortDate(hovered.date)} · No conversations`
            : `${shortDate(hovered.date)} · ${hovered.rate.toFixed(0)}% (${hovered.failures} of ${hovered.conversations})`;
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
