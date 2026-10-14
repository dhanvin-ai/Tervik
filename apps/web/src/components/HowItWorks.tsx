// "How it works": Tervik's four layers as an exploded isometric stack, each
// plate joined to a card that explains it. Drawn in SVG in a 2000 × 1040 design
// space; the stack occupies the middle 760 units and the cards sit either side.
//
// Motion: as the section scrolls in, the layers spread apart from a tight stack;
// then each plays its own part (the trace types out, a scan finds the failures,
// the network draws itself and carries pulses, the mark rises). Hovering a card
// or a layer lifts that layer and highlights its card.
import { useState, type CSSProperties, type ReactNode } from 'react';
import { TERVIK_PANELS } from './TervikLogo';
import { usePrefersReducedMotion } from '../hooks/useMotion';

const CX = 1000;   // the stack's centre line
const W = 265;     // half a plate's width on screen
const H = 133;     // half its depth on screen: a 2:1 isometric plate
const T = 16;      // its thickness

type Point = [number, number];
type LayerNumber = 1 | 2 | 3 | 4;
const points = (list: Point[]) => list.map(([x, y]) => `${x},${y}`).join(' ');

/** Maps a plate's flat 100 × 100 surface onto its top face. */
const face = (cy: number) => `matrix(${W / 100} ${H / 100} ${-W / 100} ${H / 100} ${CX} ${cy - H})`;
/** A point on a plate's surface, in screen space. */
const onFace = (cy: number, u: number, v: number): Point => [CX + (u - v) * W / 100, cy - H + (u + v) * H / 100];
const rhombus = (cy: number) => points([[CX, cy - H], [CX + W, cy], [CX, cy + H], [CX - W, cy]]);

const PLATE_Y: Record<LayerNumber, number> = { 1: 840, 2: 618, 3: 430, 4: 232 };
// Before the stack spreads apart, every layer sits this far from its place, bunched around the middle.
const GATHER: Record<LayerNumber, number> = { 1: -150, 2: -55, 3: 40, 4: 150 };

function Plate({ cy, top, left, right, edge, children }: { cy: number; top: string; left: string; right: string; edge: string; children?: ReactNode }) {
  return <g>
    <polygon points={points([[CX - W, cy], [CX, cy + H], [CX, cy + H + T], [CX - W, cy + T]])} fill={left} />
    <polygon points={points([[CX, cy + H], [CX + W, cy], [CX + W, cy + T], [CX, cy + H + T]])} fill={right} />
    <polygon points={rhombus(cy)} fill={top} stroke={edge} strokeWidth="1.5" strokeLinejoin="round" />
    <g transform={face(cy)} clipPath="url(#hiw-face)">{children}</g>
  </g>;
}

// Layer 1: a recorded turn, printed on the plate.
const TRACE: [string, string][] = [
  ['› where is my refund for order #4821?', 'is-prompt'],
  ['  ├ lookup_order        84 ms   ok', ''],
  ['  ├ refund_payment     4.1 s    timeout', 'is-error'],
  ['  └ send_receipt          —     skipped', ''],
  ['‹ Refund issued. You’ll see it in 3–5 days.', 'is-prompt'],
  ['  1 turn · 3 tool calls · 4.3 s · $0.004', 'is-meta'],
];

// Layer 2: conversations as cells; the flagged ones light up, in this order.
const GRID = 11;
const FLAGGED = [60, 25, 83, 14, 101, 37, 72, 3, 116, 52, 95, 26, 108, 61];

// Layer 3: recorded cases and their replays, as a network. Seeded, so it never changes.
function network() {
  let seed = 7;
  const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const hubs: Point[] = [[28, 34], [72, 18], [106, 26], [22, 88], [62, 62], [98, 80], [48, 106]];
  const nodes = hubs.flatMap(([u, v]) => [
    { u, v, z: 0, hub: true },
    ...Array.from({ length: 6 }, () => ({ u: u + (random() - .5) * 34, v: v + (random() - .5) * 34, z: (random() - .5) * 34, hub: false })),
  ]);
  const edges: [number, number][] = [];
  nodes.forEach((node, i) => {
    const near = nodes.map((other, j) => ({ j, d: Math.hypot(other.u - node.u, other.v - node.v) }))
      .filter(({ j }) => j !== i).sort((a, b) => a.d - b.d).slice(0, 2);
    near.forEach(({ j }) => { if (!edges.some(([a, b]) => (a === i && b === j) || (a === j && b === i))) edges.push([i, j]); });
  });
  hubs.forEach((_, hub) => { if (hub) edges.push([(hub - 1) * 7, hub * 7]); });
  const at = (index: number): Point => {
    const [x, y] = onFace(PLATE_Y[3], nodes[index].u, nodes[index].v);
    return [x, y + nodes[index].z];
  };
  return { nodes: nodes.map((node, index) => ({ ...node, at: at(index) })), edges: edges.map(([a, b]) => [at(a), at(b)] as [Point, Point]) };
}
const NETWORK = network();
// The edges that carry a travelling pulse: the links between hubs, which come last.
const PULSES = NETWORK.edges.slice(-6);

const LAYERS: { n: LayerNumber; title: string; lead: string; text: string; side: 'left' | 'right' }[] = [
  { n: 4, title: 'Governance', lead: 'The layer your team acts on.', text: 'An LLM reviewer checks your policies on every turn and cites the messages. Alerts reach Slack, email, or a webhook when a rate crosses its threshold.', side: 'right' },
  { n: 3, title: 'Evaluation', lead: 'Prove a fix before it ships.', text: 'Replay a candidate prompt against the recorded failures and healthy controls, then compare the flagged rate before and after.', side: 'left' },
  { n: 2, title: 'Detection', lead: 'Every failure, flagged with evidence.', text: 'Versioned rules flag corrections, frustration, failed tools, made-up values, and claims no tool backs, each citing the exact message.', side: 'right' },
  { n: 1, title: 'Observability', lead: 'The raw record of every conversation.', text: 'A user message, the agent’s reply, and every tool call in between, with results, latency, and cost, in order.', side: 'left' },
];

/** One layer of the stack, in the groups its motions need: appearing, spreading
 * apart on scroll, lifting on hover, and floating. */
function Layer({ n, active, onActive, children }: { n: LayerNumber; active: LayerNumber | null; onActive: (n: LayerNumber | null) => void; children: ReactNode }) {
  return <g className={`hiw-layer ${active === n ? 'is-active' : ''}`} style={{ '--i': 4 - n, '--gather': `${GATHER[n]}px` } as CSSProperties}
    onMouseEnter={() => onActive(n)} onMouseLeave={() => onActive(null)}>
    <g className="hiw-spread"><g className="hiw-lift"><g className="hiw-float">{children}</g></g></g>
  </g>;
}

/** The exploded stack on its own. */
export function LayerStack({ active = null, onActive = () => {}, className = '' }: { active?: LayerNumber | null; onActive?: (n: LayerNumber | null) => void; className?: string }) {
  const reduced = usePrefersReducedMotion();
  const markScale = .15;
  return <svg className={`hiw-stack ${className}`} viewBox="620 0 760 1040" role="img"
    aria-label="Tervik's four layers, stacked: observability at the bottom, then detection, evaluation, and governance on top">
    <defs>
      <clipPath id="hiw-face" clipPathUnits="userSpaceOnUse"><rect width="100" height="100" rx="3" /></clipPath>
      <linearGradient id="hiw-silver" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#fafafa" /><stop offset=".55" stopColor="#cfcfcf" /><stop offset="1" stopColor="#9a9a9a" />
      </linearGradient>
      <linearGradient id="hiw-dark" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#1c1c1c" /><stop offset="1" stopColor="#0b0b0b" />
      </linearGradient>
      <pattern id="hiw-brushed" width="2" height="2" patternUnits="userSpaceOnUse"><rect width="2" height=".6" fill="rgba(0,0,0,.06)" /></pattern>
      <radialGradient id="hiw-halo"><stop offset="0" stopColor="#fff" stopOpacity=".22" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></radialGradient>
      <filter id="hiw-glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="3.5" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
      </filter>
    </defs>

    {/* Layer 1: Observability. The trace types out, line by line. */}
    <Layer n={1} active={active} onActive={onActive}>
      <Plate cy={PLATE_Y[1]} top="url(#hiw-dark)" left="#050505" right="#0a0a0a" edge="rgba(255,255,255,.2)">
        {TRACE.map(([line, kind], index) => <text key={index} x="20" y={40 + index * 8.2} className={`hiw-trace ${kind}`}
          style={{ '--line': index } as CSSProperties}>{line}</text>)}
        <rect className="hiw-caret" x="20" y={40 + TRACE.length * 8.2 - 2.6} width="1.6" height="3" />
      </Plate>
    </Layer>

    {/* Layer 2: Detection. A scan sweeps the conversations, and the failures light up. */}
    <Layer n={2} active={active} onActive={onActive}>
      <ellipse className="hiw-halo" cx={CX} cy={PLATE_Y[2] + 10} rx={W * 1.05} ry={H * 1.1} fill="url(#hiw-halo)" />
      <Plate cy={PLATE_Y[2]} top="#141414" left="#2c2c2c" right="#3a3a3a" edge="rgba(255,255,255,.35)">
        {Array.from({ length: GRID * GRID }, (_, index) => {
          const order = FLAGGED.indexOf(index);
          return <rect key={index} x={6 + (index % GRID) * 8} y={6 + Math.floor(index / GRID) * 8} width="6.4" height="6.4" rx=".8"
            className={order >= 0 ? 'hiw-cell is-flagged' : 'hiw-cell'}
            style={{ '--k': (index % GRID) + Math.floor(index / GRID), ...(order >= 0 ? { '--o': order } : {}) } as CSSProperties} />;
        })}
      </Plate>
    </Layer>

    {/* Layer 3: Evaluation. The network draws itself, then pulses travel along it. */}
    <Layer n={3} active={active} onActive={onActive}>
      <polygon points={rhombus(PLATE_Y[3])} fill="transparent" />
      {NETWORK.edges.map(([[x1, y1], [x2, y2]], index) => <line key={index} x1={x1} y1={y1} x2={x2} y2={y2} pathLength={1}
        className="hiw-edge" style={{ '--e': index } as CSSProperties} />)}
      <g filter="url(#hiw-glow)">
        {NETWORK.nodes.map((node, index) => <circle key={index} cx={node.at[0]} cy={node.at[1]} r={node.hub ? 7 : 4}
          className={node.hub ? 'hiw-node is-hub' : 'hiw-node'} style={{ '--d': `${(index % 6) * .55}s`, '--e': index * .6 } as CSSProperties} />)}
        {/* Each pulse stays hidden until it starts moving, or it would sit at the origin. */}
        {!reduced && PULSES.map(([[x1, y1], [x2, y2]], index) => <circle key={`pulse-${index}`} r="3" className="hiw-pulse" visibility="hidden">
          <set attributeName="visibility" to="visible" begin={`${1.5 + index * .45}s`} />
          <animateMotion dur={`${2.2 + (index % 3) * .5}s`} begin={`${1.5 + index * .45}s`} repeatCount="indefinite" path={`M${x1},${y1} L${x2},${y2}`} />
        </circle>)}
      </g>
    </Layer>

    {/* Layer 4: Governance. The Tervik mark rises out of a silver plate. */}
    <Layer n={4} active={active} onActive={onActive}>
      <Plate cy={PLATE_Y[4]} top="url(#hiw-silver)" left="#5f5f5f" right="#7d7d7d" edge="rgba(255,255,255,.9)">
        <rect width="100" height="100" fill="url(#hiw-brushed)" />
      </Plate>
      {Array.from({ length: 14 }, (_, step) => (
        <g key={step} className="hiw-rise" style={{ '--s': step } as CSSProperties}>
          <g transform={face(PLATE_Y[4])}><g transform={`translate(${50 - 345 * markScale / 2} ${50 - 323 * markScale / 2}) scale(${markScale})`}>
            {TERVIK_PANELS.map((d, index) => <path key={index} d={d} fill={step === 13 ? '#fdfdfd' : index === 1 ? '#8c8c8c' : '#6f6f6f'}
              stroke={step === 13 ? 'rgba(0,0,0,.18)' : 'none'} strokeWidth="3" />)}
          </g></g>
        </g>
      ))}
    </Layer>
  </svg>;
}

/** The section: the stack in the middle, a card for each layer either side. */
export function HowItWorks() {
  const [active, setActive] = useState<LayerNumber | null>(null);
  return <section id="how-it-works" className="lp-section hiw-section">
    <div className="lp-container">
      <h2 className="lp-heading hiw-title">
        <span className="lp-mask" data-reveal="rise"><span>How it works</span></span>
      </h2>
      <div className={`hiw ${active ? 'has-active' : ''}`} data-reveal="fade">
        <LayerStack active={active} onActive={setActive} />
        {LAYERS.map(layer => <article key={layer.n} tabIndex={0} className={`hiw-card is-${layer.side} ${active === layer.n ? 'is-active' : ''}`}
          style={{ '--y': `${(PLATE_Y[layer.n] / 1040) * 100}%`, '--i': 4 - layer.n } as CSSProperties}
          onMouseEnter={() => setActive(layer.n)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(layer.n)} onBlur={() => setActive(null)}>
          <header><span className="hiw-tag">Layer {layer.n}</span><h3>{layer.title}</h3></header>
          <p className="hiw-lead">{layer.lead}</p>
          <p className="hiw-text">{layer.text}</p>
        </article>)}
      </div>
    </div>
  </section>;
}
