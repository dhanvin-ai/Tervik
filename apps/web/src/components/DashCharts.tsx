// Line charts for the overview: thin lines, hollow point markers, plain gridlines.
// Each chart measures its own width and draws at that size, so text and strokes
// keep the same size however wide the panel is.
import { useLayoutEffect, useRef, useState } from 'react';

type Day = { date: string; conversations: number; failures: number };

const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

/** Rounds a rough step up to 1, 2, 2.5, or 5 times a power of ten. */
function niceStep(rough: number) {
  const power = 10 ** Math.floor(Math.log10(Math.max(rough, 1e-9)));
  const scaled = rough / power;
  return (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10) * power;
}

/** A whole-number step of 1, 2, or 5 times a power of ten. */
function countStep(rough: number) {
  const power = 10 ** Math.floor(Math.log10(Math.max(rough, 1)));
  const scaled = rough / power;
  return Math.max(1, (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10) * power);
}

/** The element's width in pixels, kept up to date as it resizes. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(Math.max(240, Math.round(element.getBoundingClientRect().width)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Day indexes to label: spread evenly from the first day to the last, as many as fit. */
function labelIndexes(count: number, plotWidth: number) {
  const fits = Math.max(2, Math.floor(plotWidth / 54));  // "10 Oct" plus a gap
  const stride = Math.max(1, Math.ceil((count - 1) / (fits - 1)));
  const indexes: number[] = [];
  for (let index = 0; index < count; index += stride) indexes.push(index);
  const last = count - 1;
  if (last > 0 && indexes[indexes.length - 1] !== last) {
    // Too close to the previous label: the last day takes its place.
    if (last - indexes[indexes.length - 1] <= stride / 2) indexes[indexes.length - 1] = last;
    else indexes.push(last);
  }
  return indexes;
}

type Frame = { width: number; height: number; left: number; right: number; top: number; bottom: number };

/** Gridlines, value labels, date labels, and a hover band per day. */
function Axes({ frame, ticks, y, format, dates, onHover }: {
  frame: Frame; ticks: number[]; y: (value: number) => number; format: (tick: number) => string;
  dates: string[]; onHover: (index: number) => void;
}) {
  const { width, height, left, right, top, bottom } = frame;
  const band = (width - left - right) / Math.max(1, dates.length - 1);
  const x = (index: number) => left + index * band;
  return <>
    {ticks.map(tick => <g key={tick}>
      <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="dash-rate-grid" />
      <text x={4} y={y(tick) + 4} className="dash-rate-axis">{format(tick)}</text>
    </g>)}
    {labelIndexes(dates.length, width - left - right).map(index => <text key={dates[index]} x={x(index)} y={height - 6} textAnchor="middle" className="dash-rate-axis">{shortDate(dates[index])}</text>)}
    {dates.map((date, index) => <rect key={date} x={x(index) - band / 2} y={top} width={band} height={height - top - bottom} fill="transparent" onMouseEnter={() => onHover(index)} />)}
  </>;
}

/** A tooltip box above a point, kept inside the plot. */
function Tip({ frame, x, y, lines }: { frame: Frame; x: number; y: number; lines: string[] }) {
  const boxWidth = Math.max(...lines.map(line => line.length)) * 7 + 18;
  const boxHeight = lines.length * 16 + 8;
  const boxX = Math.min(Math.max(x - boxWidth / 2, frame.left), frame.width - frame.right - boxWidth);
  const boxY = Math.max(y - boxHeight - 12, 0);
  return <g className="dash-rate-tip" pointerEvents="none">
    <rect x={boxX} y={boxY} width={boxWidth} height={boxHeight} rx={3} />
    {lines.map((line, index) => <text key={index} x={boxX + boxWidth / 2} y={boxY + 18 + index * 16} textAnchor="middle">{line}</text>)}
  </g>;
}

/** Daily problem rate across every day of the range. A day without conversations
 * has no rate: it sits on the baseline as a faint point joined by a dashed line,
 * so the line spans the whole range without passing those days off as 0%. */
export function RateChart({ trend, summary }: { trend: Day[]; summary: string }) {
  const [ref, width] = useWidth(520);
  const [active, setActive] = useState<number | null>(null);
  const frame: Frame = { width, height: 230, left: 44, right: 20, top: 12, bottom: 30 };
  const days = trend.map((day, index) => ({ ...day, index, rate: day.conversations ? (100 * day.failures) / day.conversations : null }));
  const rates = days.flatMap(day => day.rate === null ? [] : [day.rate]);
  const step = Math.min(50, niceStep(Math.max(...rates, 10) / 3));
  const maximum = Math.min(100, Math.ceil(Math.max(...rates, step) / step) * step);
  const ticks = Array.from({ length: Math.round(maximum / step) + 1 }, (_, i) => i * step);
  const band = (width - frame.left - frame.right) / Math.max(1, days.length - 1);
  const x = (index: number) => frame.left + index * band;
  const y = (rate: number | null) => frame.top + (1 - (rate ?? 0) / maximum) * (frame.height - frame.top - frame.bottom);
  const hovered = active !== null ? days[active] : undefined;
  return (
    <figure className="dash-rate" onMouseLeave={() => setActive(null)}>
      <figcaption className="dash-rate-title">{summary}</figcaption>
      <div ref={ref} className="dash-chart">
        <svg viewBox={`0 0 ${width} ${frame.height}`} width={width} height={frame.height} role="img" aria-label={rates.length ? `Daily problem rate over ${days.length} days, from ${rates[0].toFixed(0)} to ${rates[rates.length - 1].toFixed(0)} percent` : 'No conversations in this period'}>
          <Axes frame={frame} ticks={ticks} y={y} format={tick => `${Number.isInteger(tick) ? tick : tick.toFixed(1)}%`} dates={days.map(day => day.date)} onHover={setActive} />
          {days.slice(1).map((day, i) => {
            const previous = days[i];
            const measured = previous.rate !== null && day.rate !== null;
            return <path key={day.date} d={`M${x(previous.index).toFixed(1)},${y(previous.rate).toFixed(1)} L${x(day.index).toFixed(1)},${y(day.rate).toFixed(1)}`}
              className={measured ? 'dash-rate-line' : 'dash-rate-gap'} />;
          })}
          {days.map(day => day.rate === null
            ? <circle key={day.date} cx={x(day.index)} cy={y(null)} r={active === day.index ? 3.5 : 2.2} className="dash-rate-empty" />
            : <circle key={day.date} cx={x(day.index)} cy={y(day.rate)} r={active === day.index ? 5 : 3.5} className="dash-rate-point" />)}
          {hovered && <Tip frame={frame} x={x(hovered.index)} y={y(hovered.rate)} lines={[hovered.rate === null
            ? `${shortDate(hovered.date)} · No conversations`
            : `${shortDate(hovered.date)} · ${hovered.rate.toFixed(0)}% (${hovered.failures} of ${hovered.conversations})`]} />}
        </svg>
      </div>
    </figure>
  );
}

/** Conversations per day, and how many of them had a problem. */
export function CountChart({ trend }: { trend: Day[] }) {
  const [ref, width] = useWidth(960);
  const [active, setActive] = useState<number | null>(null);
  const peak = Math.max(...trend.map(day => day.conversations), 0);
  const step = countStep(peak / 4);
  const maximum = Math.max(step, Math.ceil(peak / step) * step);
  const ticks = Array.from({ length: Math.round(maximum / step) + 1 }, (_, i) => i * step);
  const frame: Frame = { width, height: 220, left: String(maximum).length * 8 + 22, right: 20, top: 12, bottom: 30 };
  const band = (width - frame.left - frame.right) / Math.max(1, trend.length - 1);
  const x = (index: number) => frame.left + index * band;
  const y = (value: number) => frame.top + (1 - value / maximum) * (frame.height - frame.top - frame.bottom);
  const path = (key: 'conversations' | 'failures') => trend.map((day, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(day[key]).toFixed(1)}`).join(' ');
  const hovered = active !== null ? trend[active] : undefined;
  return (
    <div ref={ref} className="dash-chart dash-count" onMouseLeave={() => setActive(null)}>
      <svg viewBox={`0 0 ${width} ${frame.height}`} width={width} height={frame.height} role="img"
        aria-label={`Conversations per day over ${trend.length} days: ${trend.reduce((sum, day) => sum + day.conversations, 0)} in total, ${trend.reduce((sum, day) => sum + day.failures, 0)} with a problem`}>
        <Axes frame={frame} ticks={ticks} y={y} format={tick => String(tick)} dates={trend.map(day => day.date)} onHover={setActive} />
        {active !== null && <line x1={x(active)} x2={x(active)} y1={frame.top} y2={frame.height - frame.bottom} className="dash-chart-guide" />}
        <path d={path('conversations')} className="dash-count-line" />
        <path d={path('failures')} className="dash-count-line failures" />
        {trend.map((day, i) => <g key={day.date}>
          <circle cx={x(i)} cy={y(day.conversations)} r={active === i ? 5 : 3.5} className="dash-count-point" />
          <circle cx={x(i)} cy={y(day.failures)} r={active === i ? 5 : 3.5} className="dash-count-point failures" />
        </g>)}
        {hovered && active !== null && <Tip frame={frame} x={x(active)} y={y(hovered.conversations)} lines={[
          shortDate(hovered.date),
          `${hovered.conversations} ${hovered.conversations === 1 ? 'conversation' : 'conversations'} · ${hovered.failures} with a problem`]} />}
      </svg>
    </div>
  );
}
