// Small dotted charts for the overview, drawn in the landing page's dithered style.
import { useId } from 'react';

type Day = { date: string; conversations: number; failures: number };

function DotPattern({ id, color, size = 2.6, gap = 4 }: { id: string; color: string; size?: number; gap?: number }) {
  return <pattern id={id} width={gap} height={gap} patternUnits="userSpaceOnUse"><rect width={size} height={size} fill={color} /></pattern>;
}

const shortDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

/** Daily flagged rate as a stepped dotted area with square markers. */
export function RateChart({ trend }: { trend: Day[] }) {
  const id = useId().replace(/:/g, '');
  const width = 420, height = 170, left = 30, right = 12, top = 14, bottom = 26;
  const points = trend.map((day, index) => ({ index, date: day.date, rate: day.conversations ? (100 * day.failures) / day.conversations : null }));
  const known = points.filter((point): point is { index: number; date: string; rate: number } => point.rate !== null);
  const x = (index: number) => left + (index / Math.max(1, trend.length - 1)) * (width - left - right);
  const y = (rate: number) => top + (1 - rate / 100) * (height - top - bottom);
  const steps = known.map((point, i) => (i === 0 ? `M${x(point.index)},${y(point.rate)}` : `H${x(point.index)} V${y(point.rate)}`)).join(' ');
  const area = known.length ? `${steps} V${height - bottom} H${x(known[0].index)} Z` : '';
  const peak = known.reduce<typeof known[number] | null>((best, point) => (!best || point.rate > best.rate ? point : best), null);
  const average = known.length ? known.reduce((sum, point) => sum + point.rate, 0) / known.length : 0;
  const last = known[known.length - 1];
  return (
    <figure className="dash-rate">
      <figcaption className="dash-rate-bar"><span className="lp-window-dots" aria-hidden="true"><i /><i /><i /></span>flagged rate · per day</figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={known.length ? `Daily flagged rate, averaging ${average.toFixed(1)} percent` : 'No daily data yet'}>
        <defs>
          <DotPattern id={`${id}-area`} color="rgba(255, 255, 255, 0.28)" size={2} gap={4} />
          <DotPattern id={`${id}-track`} color="rgba(255, 255, 255, 0.06)" size={1.5} gap={4} />
        </defs>
        <rect x={left} y={top} width={width - left - right} height={height - top - bottom} fill={`url(#${id}-track)`} />
        {[0, 50, 100].map(tick => <g key={tick}>
          <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke="rgba(255, 255, 255, 0.08)" strokeDasharray="2 5" />
          <text x={left - 8} y={y(tick) + 3.5} textAnchor="end">{tick}%</text>
        </g>)}
        {known.length > 0 && <>
          <path d={area} fill={`url(#${id}-area)`} />
          <path d={steps} fill="none" stroke="#f5f5f5" strokeWidth="1.6" shapeRendering="crispEdges" />
          {known.map(point => <rect key={point.date} x={x(point.index) - 3} y={y(point.rate) - 3} width="6" height="6" fill={point === last ? '#f87171' : '#f5f5f5'} />)}
          {last && (() => {
            // Latest value sits on a small plate under its marker so the step line never crosses it.
            const labelX = Math.min(x(last.index) + 4, width - right);
            const labelY = Math.min(y(last.rate) + 20, height - bottom - 4);
            return <g className="dash-rate-last">
              <rect x={labelX - 30} y={labelY - 11} width="30" height="15" fill="#0c0c0e" stroke="rgba(248, 113, 113, 0.45)" />
              <text x={labelX - 15} y={labelY} textAnchor="middle">{last.rate.toFixed(0)}%</text>
            </g>;
          })()}
        </>}
        {trend.length > 0 && <>
          <text x={left} y={height - 8}>{shortDate(trend[0].date)}</text>
          <text x={width - right} y={height - 8} textAnchor="end">{shortDate(trend[trend.length - 1].date)}</text>
        </>}
      </svg>
      <p className="dash-rate-foot">{known.length ? <>daily avg <b>{average.toFixed(1)}%</b>{peak && <> · peak <b>{peak.rate.toFixed(0)}%</b> on {shortDate(peak.date)}</>}</> : 'Daily rates appear once conversations arrive.'}</p>
    </figure>
  );
}

/** Dotted mini columns, one per value. */
export function SparkBars({ values, tone = 'gray', label }: { values: number[]; tone?: 'gray' | 'red'; label: string }) {
  const id = useId().replace(/:/g, '');
  const width = 200, height = 44;
  const max = Math.max(1, ...values);
  const band = width / Math.max(1, values.length);
  const bar = Math.max(4, band * 0.62);
  return (
    <svg className="dash-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <defs>
        <DotPattern id={`${id}-fill`} color={tone === 'red' ? '#f87171' : '#c4c4c4'} size={2.2} gap={3.5} />
        <DotPattern id={`${id}-track`} color="rgba(255, 255, 255, 0.07)" size={1.4} gap={3.5} />
      </defs>
      {values.map((value, index) => {
        const h = Math.max(value ? 3 : 0, (value / max) * (height - 2));
        const left = index * band + (band - bar) / 2;
        return <g key={index}>
          <rect x={left} y={0} width={bar} height={height} fill={`url(#${id}-track)`} />
          <rect x={left} y={height - h} width={bar} height={h} fill={`url(#${id}-fill)`} />
        </g>;
      })}
    </svg>
  );
}

/** Stepped line with square markers. */
export function SparkLine({ values, label }: { values: number[]; label: string }) {
  const width = 200, height = 44, pad = 4;
  if (!values.length) return <svg className="dash-spark" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} />;
  const max = Math.max(...values), min = Math.min(...values);
  const x = (index: number) => pad + (index / Math.max(1, values.length - 1)) * (width - pad * 2);
  const y = (value: number) => pad + (1 - (max === min ? 0.5 : (value - min) / (max - min))) * (height - pad * 2);
  const path = values.map((value, index) => (index === 0 ? `M${x(index)},${y(value)}` : `H${x(index)} V${y(value)}`)).join(' ');
  return (
    <svg className="dash-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <line x1="0" x2={width} y1={height - 1} y2={height - 1} stroke="rgba(255, 255, 255, 0.1)" strokeDasharray="2 3" />
      <path d={path} fill="none" stroke="#d4d4d4" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      {values.map((value, index) => <rect key={index} x={x(index) - 2} y={y(value) - 2} width="4" height="4" fill={index === values.length - 1 ? '#fff' : '#8a8a8a'} />)}
    </svg>
  );
}

/** Segmented dotted strip: each segment is one part's share of the total. */
export function ShareStrip({ parts, label }: { parts: { key: string; value: number; tone: 'high' | 'medium' | 'low' | 'critical' }[]; label: string }) {
  const id = useId().replace(/:/g, '');
  const total = parts.reduce((sum, part) => sum + part.value, 0) || 1;
  const width = 200, height = 44, gap = 4;
  const colors = { critical: '#f87171', high: '#f87171', medium: '#fbbf24', low: '#c4c4c4' };
  let cursor = 0;
  const usable = width - gap * Math.max(0, parts.length - 1);
  return (
    <svg className="dash-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={label}>
      <defs>{Object.entries(colors).map(([tone, color]) => <DotPattern key={tone} id={`${id}-${tone}`} color={color} size={2.2} gap={3.5} />)}</defs>
      {parts.map(part => {
        const w = (part.value / total) * usable;
        const rect = <rect key={part.key} x={cursor} y={height - 26} width={w} height={26} fill={`url(#${id}-${part.tone})`} />;
        cursor += w + gap;
        return rect;
      })}
    </svg>
  );
}
