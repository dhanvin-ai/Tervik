import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { ArrowRight, Check, Copy, Download, LoaderCircle } from 'lucide-react';
import { DitherCanvas } from './DitherCanvas';
import { DitherText } from './DitherText';
import { PixelIcon, type PixelIconName } from './PixelIcon';
import { usePrefersReducedMotion, useScrollReveal } from '../hooks/useMotion';

const INSTALL_COMMAND = 'npx skills add dhanvin-ai/tervik --skill tervik';
const INSTALL_PROMPT = 'Use the tervik skill to add Tervik analytics to this agent.';
const GITHUB_URL = 'https://github.com/dhanvin-ai/tervik';

/** Cycles 0..count-1 while the element is on screen; any manual pick stops the cycle. */
function useAutoCycle(count: number, intervalMs: number) {
  const [index, setIndex] = useState(0);
  const [manual, setManual] = useState(false);
  const reduced = usePrefersReducedMotion();
  const { ref, isRevealed } = useScrollReveal<HTMLDivElement>(0.25);
  useEffect(() => {
    if (manual || reduced || !isRevealed) return;
    const timer = setInterval(() => setIndex(value => (value + 1) % count), intervalMs);
    return () => clearInterval(timer);
  }, [count, intervalMs, manual, reduced, isRevealed]);
  return { ref, index, cycling: !manual && !reduced && isRevealed, pick: (value: number) => { setManual(true); setIndex(value); } };
}

function Heading({ title, muted, align = 'left', className = '' }: { title: string; muted: string; align?: 'left' | 'right'; className?: string }) {
  return <h2 className={`lp-heading ${align === 'right' ? 'is-right' : ''} ${className}`}>{title}<span>{muted}</span></h2>;
}

function Window({ title, children, className = '' }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`lp-window ${className}`}>
      <div className="lp-window-bar"><span className="lp-window-dots" aria-hidden="true"><i /><i /><i /></span><span>{title}</span></div>
      <div className="lp-window-body">{children}</div>
    </div>
  );
}

/* ---------- 1. Feature grid ---------- */

function TurnVisual() {
  return <>
    <Window title="conversation · support-bot" className="lp-win-a">
      <div className="lp-chat">
        <p className="lp-bubble is-user">My order #4821 arrived broken. Can I get a refund?</p>
        <p className="lp-bubble">Refund issued. You’ll see it in 3–5 days.</p>
        <p className="lp-chat-meta">2 messages · user u_7f3a · 2.3 s</p>
      </div>
    </Window>
    <Window title="trace · 5f1c" className="lp-win-b">
      <div className="lp-spans">
        <p><span>agent.turn</span><em>2.31 s</em></p>
        <p className="is-child"><span>lookup_order</span><em className="is-ok">84 ms</em></p>
        <p className="is-child"><span>refund_payment</span><em className="is-error">timeout</em></p>
      </div>
    </Window>
  </>;
}

function SignalsVisual() {
  const rows = [
    ['tool_timeout', 'high', 'refund_payment exceeded its deadline'],
    ['unsupported_claim', 'high', '“Refund issued” with no successful tool call'],
    ['correction', 'medium', '“That’s not what I asked.”'],
  ];
  return <>
    <Window title="signals · last 24 hours" className="lp-win-wide">
      <div className="lp-signal-list">
        {rows.map(([kind, severity, reason]) => <div key={kind} className="lp-signal">
          <span className={`lp-sev is-${severity}`} />
          <code>{kind}</code>
          <span>{reason}</span>
        </div>)}
      </div>
    </Window>
    <Window title="evidence · evt_9c1e" className="lp-win-evidence">
      <p className="lp-quote">“Refund issued. You’ll see it in 3–5 days.”</p>
      <p className="lp-chat-meta">detector 5.0.0 · rule unsupported_claim</p>
    </Window>
  </>;
}

function ClustersVisual() {
  const rows: [string, number][] = [['refund · order · broken', 42], ['billing · address · change', 17], ['password · reset · link', 9]];
  return (
    <Window title="discovery · last 7 days" className="lp-win-wide">
      <div className="lp-cluster-list">
        {rows.map(([label, count]) => <div key={label} className="lp-cluster">
          <span>{label}</span>
          <span className="lp-meter" style={{ '--fill': `${(count / 42) * 100}%` } as CSSProperties} />
          <em>{count}</em>
        </div>)}
      </div>
      <p className="lp-chat-meta">312 of 340 conversations grouped · 97 users affected</p>
    </Window>
  );
}

function ReplayVisual() {
  return (
    <Window title="replay · refund-timeouts v2" className="lp-win-wide lp-win-mono">
      <p className="lp-term-muted">42 recorded cases · 3 repeats · tools served from fixtures</p>
      <p><span className="lp-term-key">baseline</span>  31 / 42 passed</p>
      <p><span className="lp-term-key">candidate</span> 42 / 42 passed</p>
      <p><span className="lp-term-key">fixed</span>     11  <span className="lp-term-key">regressed</span> 0</p>
      <p className="lp-term-ok">verdict: improved · reproducible<span className="lp-cursor" /></p>
    </Window>
  );
}

const FEATURES: { lead: string; text: string; visual: ReactNode; seed: number }[] = [
  { lead: 'Every turn, recorded.', text: 'User messages, model calls, and nested tool spans arrive with stable IDs, so retries and late events never double count.', visual: <TurnVisual />, seed: 1 },
  { lead: 'Failures backed by evidence.', text: 'Versioned detectors flag corrections, frustration, timeouts, and claims no tool supports, each citing the exact message.', visual: <SignalsVisual />, seed: 2.4 },
  { lead: 'Recurring problems, grouped.', text: 'Similar conversations cluster together with counts of affected users, so you fix what hurts the most people first.', visual: <ClustersVisual />, seed: 3.7 },
  { lead: 'Fixes you can prove.', text: 'Replay a candidate prompt against recorded failures and healthy controls before anything reaches production.', visual: <ReplayVisual />, seed: 5.2 },
];

export function FeatureShowcase() {
  const { ref, isRevealed } = useScrollReveal<HTMLDivElement>(0.1);
  return (
    <section id="features" className="lp-section lp-section-first">
      <div className="lp-container">
        <Heading title="Know exactly where your agent fails." muted="Every turn recorded, every signal tied to evidence." />
        <div ref={ref} className={`lp-feature-grid ${isRevealed ? 'is-revealed' : ''}`}>
          {FEATURES.map(({ lead, text, visual, seed }) => <article key={lead} className="lp-feature">
            <div className="lp-visual">
              <DitherCanvas seed={seed} vignette={0.8} intensity={1.15} />
              <div className="lp-visual-stage">{visual}</div>
            </div>
            <p className="lp-caption"><strong>{lead}</strong> {text}</p>
          </article>)}
        </div>
      </div>
    </section>
  );
}

/* ---------- 2. Divider ---------- */

export function DitherDivider() {
  return <div className="lp-divider" aria-hidden="true"><DitherCanvas vignette={0} intensity={0.6} scale={1.6} speed={0.6} seed={9} /></div>;
}

/* ---------- 3. Principles grid ---------- */

function OutboxArt() {
  const rows: [string, number, string][] = [['processed', 14, '12,480'], ['pending', 1, '3'], ['failed', 0, '0'], ['dead', 0, '0']];
  return (
    <div className="lp-ascii">
      <p className="lp-ascii-cmd">ingestion jobs · support-bot</p>
      {rows.map(([label, blocks, count]) => <p key={label}>
        <span className="lp-ascii-label">{label}</span>
        <span className="lp-ascii-bar">{'█'.repeat(blocks)}<span>{'░'.repeat(15 - blocks)}</span></span>
        <span className="lp-ascii-count">{count}</span>
      </p>)}
    </div>
  );
}

function StackArt() {
  // Four dotted isometric slabs: ingest, detect, cluster, replay.
  const slab = (y: number, key: number) => <g key={key} transform={`translate(0 ${y})`}>
    <path d="M100 10 L180 50 L100 90 L20 50 Z" fill="url(#lp-dots-top)" />
    <path d="M20 50 L100 90 L100 104 L20 64 Z" fill="url(#lp-dots-left)" />
    <path d="M100 90 L180 50 L180 64 L100 104 Z" fill="url(#lp-dots-right)" />
  </g>;
  return (
    <svg className="lp-stack" viewBox="0 0 200 200" aria-hidden="true">
      <defs>
        <pattern id="lp-dots-top" width="3" height="3" patternUnits="userSpaceOnUse"><rect width="1.6" height="1.6" fill="#d4d4d4" /></pattern>
        <pattern id="lp-dots-left" width="3" height="3" patternUnits="userSpaceOnUse"><rect width="1.3" height="1.3" fill="#7a7a7a" /></pattern>
        <pattern id="lp-dots-right" width="3" height="3" patternUnits="userSpaceOnUse"><rect width="1" height="1" fill="#555" /></pattern>
      </defs>
      {[96, 64, 32, 0].map((y, index) => slab(y, index))}
    </svg>
  );
}

function GaugeArt() {
  const gauge = (value: number, label: string, angle: number) => <figure className="lp-gauge">
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <rect x="44" y="2" width="12" height="6" fill="#8a8a8a" />
      <circle cx="50" cy="56" r="38" fill="none" stroke="#9a9a9a" strokeWidth="2.4" strokeDasharray="1.4 2.2" />
      {Array.from({ length: 12 }, (_, i) => <rect key={i} x="49" y="20" width="2" height="4" fill="#6a6a6a" transform={`rotate(${i * 30} 50 56)`} />)}
      <line x1="50" y1="56" x2="50" y2="28" stroke="#e5e5e5" strokeWidth="3" strokeDasharray="2 1.2" transform={`rotate(${angle} 50 56)`} />
      <rect x="47" y="53" width="6" height="6" fill="#e5e5e5" />
    </svg>
    <figcaption>{value.toFixed(1)}%<small>{label}</small></figcaption>
  </figure>;
  return <div className="lp-gauges">{gauge(18.2, 'before', 64)}{gauge(4.6, 'after', 16)}</div>;
}

const PRINCIPLES = [
  { title: 'A durable outbox.', text: 'Events commit before they are acknowledged. Restarts, retries, and late arrivals never lose or double count a turn.', art: <OutboxArt /> },
  { title: 'Rules you can read.', text: 'Detectors are versioned regex and tool-evidence checks, not a model judging a model. Same input, same verdict.', art: <StackArt /> },
  { title: 'Measured outcomes.', text: 'Each deployed fix is compared against the flagged rate it was meant to reduce, with the windows on record.', art: <GaugeArt /> },
];

export function PrinciplesGrid() {
  return (
    <section id="how-it-works" className="lp-section">
      <div className="lp-container">
        <Heading title="Every signal is deterministic," muted="versioned, and tied to a recorded event." />
        <div className="lp-principles">
          {PRINCIPLES.map(item => <div key={item.title} className="lp-principle">
            <h3>{item.title}</h3>
            <p>{item.text}</p>
            <div className="lp-principle-art">{item.art}</div>
          </div>)}
        </div>
      </div>
    </section>
  );
}

/* ---------- 4. Turn walkthrough (tabs) ---------- */

const STAGES: { icon: PixelIconName; title: string; text: string }[] = [
  { icon: 'ingest', title: 'Ingest', text: 'The turn is buffered and exported off the response path.' },
  { icon: 'trace', title: 'Trace', text: 'Each tool call becomes a span with input, output, and latency.' },
  { icon: 'detect', title: 'Detect', text: 'A deterministic rule flags the timeout and cites the span.' },
  { icon: 'cluster', title: 'Cluster', text: 'Matching failures across sessions group into one issue.' },
  { icon: 'replay', title: 'Replay', text: 'The candidate fix replays against the recorded failures.' },
];

function StagePanel({ stage, onStart }: { stage: number; onStart: () => void }) {
  const spans: [string, string, string][] = [
    ['verify_database_connection', '14 ms', '200'],
    ['check_migration_checksums', '38 ms', '200'],
    ['execute_migration', stage >= 4 ? '130 ms' : '4,120 ms', stage >= 4 ? 'retry ok' : '504'],
  ];
  const fixed = stage >= 4;
  return (
    <div className="lp-run">
      <div className="lp-run-bar">
        <span className="lp-window-dots" aria-hidden="true"><i /><i /><i /></span>
        <span>run <b>#exec-8192</b></span>
        <span>latency <b>{stage === 0 ? '12 ms' : fixed ? '182 ms' : '4.1 s'}</b></span>
        <span>tokens <b>{stage === 0 ? '48' : '342'}</b></span>
        <span className="lp-run-stage">0{stage + 1} {STAGES[stage].title.toLowerCase()}</span>
      </div>
      <div className="lp-run-body">
        <div className="lp-run-col">
          <p className="lp-run-label">user prompt</p>
          <p className="lp-run-prompt">Deploy the updated Stripe webhook migration to production.</p>
          <p className="lp-run-label">tool spans <span>{stage === 0 ? 'pending' : '3 dispatched'}</span></p>
          <div className="lp-run-spans">
            {spans.map(([name, time, status], index) => {
              const state = stage === 0 ? 'queued' : index === 2 && !fixed ? 'error' : 'ok';
              return <p key={name} className={`is-${state}`}><span>{name}</span><em>{stage === 0 ? 'queued' : `${time} · ${status}`}</em></p>;
            })}
          </div>
        </div>
        <div className="lp-run-col lp-run-detail" key={stage}>
          {stage === 0 && <>
            <p className="lp-run-label">ingestion <span>buffered</span></p>
            <p>The prompt is captured with a stable event ID and queued in memory. Export happens in the background, so the agent’s response is never waiting on telemetry.</p>
            <p className="lp-run-note is-info">1 event queued · 0 dropped</p>
          </>}
          {stage === 1 && <>
            <p className="lp-run-label">spans <span>recording</span></p>
            <p>Tool calls share the turn’s trace ID and point at their parent span, so the tree survives even when children arrive first.</p>
            <p className="lp-run-note is-error">execute_migration · 504 after 4,120 ms</p>
          </>}
          {stage === 2 && <>
            <p className="lp-run-label">signal <span>tool_timeout · high</span></p>
            <p>The tool reported a timeout, so the detector raises a signal that cites the span and records detector and rule versions.</p>
            <p className="lp-run-note is-error">evidence: span execute_migration · detector 5.0.0</p>
          </>}
          {stage === 3 && <>
            <p className="lp-run-label">cluster <span>42 conversations</span></p>
            <p>Timeouts from this tool across sessions roll up into one cluster with affected users and a trend against the previous window.</p>
            <button className="lp-text-link" onClick={onStart}>Investigate in the dashboard<ArrowRight size={14} /></button>
          </>}
          {stage === 4 && <>
            <p className="lp-run-label">replay <span>verified</span></p>
            <p>A candidate with a bounded retry replays the recorded failures with fixture-served tools. Nothing touches production.</p>
            <p className="lp-run-note is-ok">baseline 0 / 42 · candidate 42 / 42 · regressed 0</p>
          </>}
        </div>
      </div>
    </div>
  );
}

export function TurnWalkthrough({ onStart }: { onStart: () => void }) {
  const { ref, index, cycling, pick } = useAutoCycle(STAGES.length, 4200);
  return (
    <section id="walkthrough" className="lp-section">
      <div className="lp-container">
        <div className="lp-heading-row">
          <Heading title="Follow one turn through Tervik." muted="From the first prompt to a verified fix." />
          <div className="lp-heading-actions">
            <button className="lp-btn" onClick={onStart}>Open the dashboard<ArrowRight size={15} /></button>
            <span>Runs locally. No account needed.</span>
          </div>
        </div>
        <div ref={ref} className="lp-tabs">
          <div className="lp-tab-list" role="tablist" aria-label="Turn stages">
            {STAGES.map((item, i) => <button key={item.title} role="tab" aria-selected={index === i} aria-controls="lp-stage-panel"
              className={`lp-tab ${index === i ? 'is-active' : ''}`} onClick={() => pick(i)}>
              {index === i && <DitherCanvas className="lp-tab-dither" vignette={0} intensity={0.8} seed={i} />}
              <span className="lp-tab-icon"><PixelIcon name={item.icon} /></span>
              <span className="lp-tab-text"><strong>{item.title}</strong><span>{item.text}</span></span>
              {index === i && cycling && <span className="lp-tab-progress" key={`p-${i}`} />}
            </button>)}
          </div>
          <div className="lp-tab-panel" id="lp-stage-panel" role="tabpanel"><StagePanel stage={index} onStart={onStart} /></div>
        </div>
      </div>
    </section>
  );
}

/* ---------- 5. Setup (mirrored) ---------- */

const SETUP: { icon: PixelIconName; title: string; text: string }[] = [
  { icon: 'install', title: 'Install', text: 'Add the Tervik skill to the coding agent you already use.' },
  { icon: 'prompt', title: 'Instrument', text: 'It finds your real handler and tools, then wraps them once.' },
  { icon: 'verify', title: 'Verify', text: 'Send one real turn and confirm it in your dashboard.' },
];

export function SetupSection({ onCopy, copied }: { onCopy: () => void; copied: boolean }) {
  const { ref, index, pick } = useAutoCycle(SETUP.length, 3600);
  const line = (step: number, content: ReactNode) => <span className={`lp-code-line ${index === step ? 'is-active' : ''}`}>{content}</span>;
  return (
    <section id="setup-steps" className="lp-section">
      <div className="lp-container">
        <div className="lp-heading-row is-mirrored">
          <button className="lp-btn lp-btn-outline" onClick={onCopy}>{copied ? <Check size={15} /> : <Copy size={15} />}<span aria-live="polite">{copied ? 'Command copied' : 'Copy install command'}</span></button>
          <Heading title="Set it up from your coding agent." muted="One skill. One prompt. Real traffic." align="right" />
        </div>
        <div ref={ref} className="lp-setup">
          <div className="lp-code">
            <button className="lp-code-copy" onClick={onCopy} aria-label="Copy install command">{copied ? <Check size={14} /> : <Copy size={14} />}</button>
            <pre>
              {line(0, <><span className="c">{'# 1 · add the skill to your coding agent'}</span>{'\n'}<span className="p">$</span> {INSTALL_COMMAND}{'\n'}</>)}
              {'\n'}
              {line(1, <><span className="c">{'# 2 · ask it to instrument your agent'}</span>{'\n'}<span className="p">&gt;</span> <span className="s">{INSTALL_PROMPT}</span>{'\n'}</>)}
              {'\n'}
              {line(2, <><span className="c">{'# 3 · server-side environment, then send a real turn'}</span>{'\n'}<span className="k">TERVIK_ENDPOINT</span>=<span className="s">http://127.0.0.1:8000</span>{'\n'}<span className="k">TERVIK_API_KEY</span>=<span className="s">tvk_…</span>{'\n'}</>)}
            </pre>
            <a className="lp-code-link" href="/tervik-skill.zip" download>Download skill ZIP<Download size={12} /></a>
          </div>
          <div className="lp-steps">
            {SETUP.map((step, i) => <button key={step.title} className={`lp-tab lp-step ${index === i ? 'is-active' : ''}`} onClick={() => pick(i)} aria-pressed={index === i}>
              {index === i && <DitherCanvas className="lp-tab-dither" vignette={0} intensity={0.8} seed={i + 4} />}
              <span className="lp-tab-icon"><PixelIcon name={step.icon} /></span>
              <span className="lp-tab-text"><strong>{step.title}</strong><span>{step.text}</span></span>
            </button>)}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------- 6. Dashboard showcase ---------- */

export function DashboardShowcase({ onDemo, demoBusy }: { onDemo: () => void; demoBusy: boolean }) {
  const clusters: [string, string, number, string][] = [
    ['Tool calls time out · refund_payment', 'high', 42, '+18%'],
    ['Agent claims an action without tool evidence', 'high', 23, '+6%'],
    ['Users correct the agent', 'medium', 17, '−9%'],
    ['Users repeat their requests', 'medium', 11, '−2%'],
  ];
  return (
    <section id="preview" className="lp-section">
      <div className="lp-container">
        <h2 className="lp-dither-heading"><DitherText text="See every failure in one place." /></h2>
        <div className="lp-showcase">
          <DitherCanvas tone="blue" vignette={0.45} intensity={1} scale={0.8} seed={3} />
          <Window title={<>tervik · overview <span className="lp-live">last 7 days</span></>} className="lp-dashboard">
            <div className="lp-metrics">
              {[['Conversations', '1,284'], ['Failure rate', '8.6%'], ['Affected users', '97'], ['Avg latency', '1.4 s']].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
            </div>
            <p className="lp-run-label">failure clusters</p>
            <div className="lp-dash-table">
              {clusters.map(([title, severity, count, trend]) => <div key={title}>
                <span className={`lp-sev is-${severity}`} />
                <span className="lp-dash-title">{title}</span>
                <span className="lp-meter" style={{ '--fill': `${(count / 42) * 100}%` } as CSSProperties} />
                <em>{count}</em>
                <span className={trend.startsWith('+') ? 'lp-trend-up' : 'lp-trend-down'}>{trend}</span>
              </div>)}
            </div>
          </Window>
        </div>
        <div className="lp-showcase-foot">
          <p>The dashboard ranks clusters by how many conversations they touch, links every count back to the recorded messages and spans, and keeps what you have resolved out of the way.</p>
          <button className="lp-btn" disabled={demoBusy} onClick={onDemo}>{demoBusy ? <LoaderCircle size={15} className="spin" /> : null}Explore the sample workspace<ArrowRight size={15} /></button>
        </div>
      </div>
    </section>
  );
}

/* ---------- 7. Banner + final CTA ---------- */

export function OtlpBanner() {
  return (
    <section className="lp-section lp-section-tight">
      <div className="lp-container">
        <div className="lp-banner">
          <DitherCanvas vignette={0.15} intensity={0.9} scale={0.7} seed={7} />
          <div className="lp-banner-content">
            <h3>Already exporting OpenTelemetry?<span>Send your OTLP traces to Tervik as they are.</span></h3>
            <a className="lp-btn" href="#integration">Connect an agent<ArrowRight size={15} /></a>
          </div>
        </div>
      </div>
    </section>
  );
}

export function FinalCta({ onStart }: { onStart: () => void }) {
  return (
    <section className="lp-final">
      <div className="lp-container">
        <h2 className="lp-dither-heading"><DitherText text="Find your first failure." /></h2>
        <button className="lp-btn" onClick={onStart}>Go to the dashboard<ArrowRight size={15} /></button>
      </div>
    </section>
  );
}

/* ---------- 8. Footer ---------- */

export function LandingFooter({ onStart, onDemo }: { onStart: () => void; onDemo: () => void }) {
  return (
    <footer className="lp-footer">
      <div className="lp-container">
        <div className="lp-footer-top">
          <div className="lp-footer-brand">
            <a href="#welcome" className="lp-footer-logo"><span className="lp-footer-mark" aria-hidden="true">T</span>tervik</a>
            <p>Analytics for AI agents.<br />Find failures. Follow the evidence.</p>
            <a className="lp-footer-mail" href={GITHUB_URL} target="_blank" rel="noreferrer">github.com/dhanvin-ai/tervik</a>
          </div>
          <nav className="lp-footer-cols" aria-label="Footer">
            <div><h4>Product</h4><button onClick={onStart}>Dashboard</button><button onClick={onDemo}>Sample workspace</button><a href="#integration">Integration</a><a href="/tervik-skill.zip" download>Skill ZIP</a></div>
            <div><h4>Works with</h4>{['Claude Code', 'Cursor', 'OpenCode', 'Codex', 'LangChain'].map(name => <a key={name} href="#setup-steps">{name}</a>)}</div>
            <div><h4>Learn</h4><a href="#features">Features</a><a href="#how-it-works">How it works</a><a href="#walkthrough">Walkthrough</a><a href="#setup-steps">Setup</a></div>
            <div><h4>Source</h4><a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub</a><a href={`${GITHUB_URL}#readme`} target="_blank" rel="noreferrer">README</a></div>
          </nav>
        </div>
        <div className="lp-footer-bottom">
          <span>&copy; {new Date().getFullYear()} Tervik. All rights reserved.</span>
          <span>Runs on your machine.</span>
        </div>
      </div>
    </footer>
  );
}
