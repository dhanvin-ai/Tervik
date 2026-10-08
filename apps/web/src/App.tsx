import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, Bot, Check,
  CheckCheck, ChevronDown, ChevronRight, ChevronUp, CircleHelp, Clock3, Code2, Copy,
  Download, ExternalLink, Eye, EyeOff, FileCode2, Filter, FolderPlus, GitBranch,
  Layers3, LayoutDashboard, LoaderCircle, Menu, MessageSquare, Pause, Play, Plus,
  RotateCcw, Search, Settings2, ShieldCheck, Sparkles, Terminal, TriangleAlert, Users, X,
  Zap, type LucideIcon,
} from 'lucide-react';
import { query, request } from './api';
import type { AlertRule, BehaviorRule, Cluster, ClusterDetail, Conversation, ConversationDetail, Delivery, Discovery, DiscoveryIntent, EvalDataset, EvalRun, Improvement, Overview, Page, Project, Range, SetupStatus } from './types';

const INSTALL_COMMAND = 'npx skills add dhanvin-ai/tervik --skill tervik';
const INSTALL_PROMPT = 'Use the tervik skill to add Tervik analytics to this agent.';
const rangeLabels: Record<Range, string> = { '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days' };
const titles: Record<Page, string> = {
  overview: 'Overview', failures: 'Failure clusters', discovery: 'Discovery',
  conversations: 'Conversations',
  integration: 'Connect your agent', welcome: 'Welcome',
};

function currentPage(): Page {
  const value = window.location.hash.replace('#', '');
  if (Object.hasOwn(titles, value)) return value as Page;
  return window.location.pathname === '/welcome' ? 'welcome' : 'overview';
}

function formatNumber(value: number) { return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value || 0); }
function money(value: number) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: value < 1 ? 3 : 2 }).format(value || 0); }
function latency(value: number) { return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value || 0)}ms`; }
function dateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function friendlyKind(value: string) { return value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()); }
function shortId(value: string) { return value.length > 20 ? `${value.slice(0, 9)}…${value.slice(-5)}` : value; }

function useResource<T>(url: string | null, refresh = 0) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(url));
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let alive = true;
    if (!url) { setData(null); setLoading(false); setError(''); return; }
    setLoading(true); setError(''); setData(null);
    request<T>(url).then(result => { if (alive) setData(result); })
      .catch(cause => { if (alive) setError(cause.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [url, refresh, retry]);
  return { data, loading, error, retry: () => setRetry(value => value + 1) };
}

function Logo({ small = false }: { small?: boolean }) {
  return <a href="#overview" className={`logo ${small ? 'logo-light' : ''}`} aria-label="Tervik overview">
    <span className="logo-symbol"><span /></span><span>tervik<span className="logo-dot">.</span></span>
  </a>;
}

function CopyButton({ text, label = 'Copy', compact = false }: { text: string; label?: string; compact?: boolean }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!copied && !error) return;
    const timer = window.setTimeout(() => { setCopied(false); setError(false); }, 2200);
    return () => window.clearTimeout(timer);
  }, [copied, error]);
  return <button className={`copy-button ${compact ? 'icon-copy' : ''}`} title={error ? 'Clipboard unavailable. Select and copy the text.' : label}
    onClick={async () => {
      try { await navigator.clipboard.writeText(text); setCopied(true); }
      catch { setError(true); }
    }} aria-label={copied ? 'Copied' : error ? 'Clipboard unavailable' : label}>
    {copied ? <Check size={15} /> : <Copy size={15} />}{!compact && (copied ? 'Copied' : error ? 'Select text' : label)}
  </button>;
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="error-state"><TriangleAlert size={23} /><div><strong>We couldn’t load this.</strong><p>{message}</p></div><button className="button button-secondary" onClick={onRetry}>Try again</button></div>;
}
function Loading({ label = 'Loading your workspace' }: { label?: string }) {
  return <div className="loading-state"><LoaderCircle size={22} className="spin" /><span>{label}</span></div>;
}
function EmptyState({ icon: Icon = MessageSquare, title, description, children }: { icon?: LucideIcon; title: string; description: string; children?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon size={25} strokeWidth={1.5} /></span><h3>{title}</h3><p>{description}</p>{children && <div className="empty-actions">{children}</div>}</div>;
}
function Status({ status }: { status: string }) {
  return <span className={`status status-${status}`}><span />{status === 'healthy' ? 'Healthy' : status === 'flagged' ? 'Flagged' : friendlyKind(status)}</span>;
}
function Severity({ severity }: { severity: string }) {
  return <span className={`severity severity-${severity}`}><span />{friendlyKind(severity)}</span>;
}

function Modal({ title, children, onClose, wide = false, sheet = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean; sheet?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current();
      if (event.key !== 'Tab') return;
      const focusable = ref.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, select, textarea, [tabindex="0"]');
      if (!focusable?.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', handle);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener('keydown', handle); previous?.focus(); };
  }, []);
  return <div className={`modal-backdrop ${sheet ? 'sheet-backdrop' : ''}`} onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} className={`modal ${wide ? 'modal-wide' : ''} ${sheet ? 'sheet' : ''}`}>
      <div className="modal-header"><span>{title}</span><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={19} /></button></div>
      {children}
    </div>
  </div>;
}

function TrendChart({ trend, range }: { trend: Overview['trend']; range: Range }) {
  const [active, setActive] = useState<number | null>(null);
  const width = 1000, height = 220, left = 42, right = 18, top = 15, bottom = 34;
  const maximum = Math.max(4, Math.ceil(Math.max(...trend.map(point => point.conversations), 0) / 4) * 4);
  const x = (index: number) => left + (index / Math.max(1, trend.length - 1)) * (width - left - right);
  const y = (value: number) => height - bottom - (value / maximum) * (height - top - bottom);
  const path = (key: 'conversations' | 'failures') => trend.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index)},${y(point[key])}`).join(' ');
  const area = trend.length ? `${path('conversations')} L${x(trend.length - 1)},${height - bottom} L${left},${height - bottom} Z` : '';
  const dateLabel = (value: string, verbose = false) => {
    const date = new Date(value);
    return range === '24h' ? date.toLocaleTimeString(undefined, { hour: 'numeric', ...(verbose ? { minute: '2-digit' } : {}) }) : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };
  const point = active !== null ? trend[active] : null;
  return <div className="chart-wrap" onMouseLeave={() => setActive(null)}>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Conversations and flagged conversations over the selected period" className="trend-chart">
      <defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4979e0" stopOpacity=".12" /><stop offset="100%" stopColor="#4979e0" stopOpacity=".0" /></linearGradient></defs>
      {[0, 1, 2, 3, 4].map(tick => <g key={tick}><line x1={left} x2={width - right} y1={y(maximum * tick / 4)} y2={y(maximum * tick / 4)} stroke="rgba(255, 255, 255, 0.06)" strokeDasharray="4 5" /><text x={left - 14} y={y(maximum * tick / 4) + 4} textAnchor="end" fontSize="10" fill="#71717a">{maximum * tick / 4}</text></g>)}
      {trend.length > 0 && <><path d={area} fill="url(#trend-fill)" /><path d={path('conversations')} fill="none" stroke="#4979e0" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" /><path d={path('failures')} fill="none" stroke="#df6a4f" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
        {trend.map((item, index) => <g key={item.date}>
          {index % Math.max(1, Math.ceil(trend.length / 7)) === 0 && <text x={x(index)} y={height - 9} textAnchor={index === 0 ? 'start' : 'middle'} fontSize="10" fill="#71717a">{dateLabel(item.date)}</text>}
          <rect x={x(index) - (width - left - right) / Math.max(1, trend.length - 1) / 2} y={top} width={(width - left - right) / Math.max(1, trend.length - 1)} height={height - top - bottom} fill="transparent" onMouseEnter={() => setActive(index)} />
        </g>)}
        {active !== null && <><line x1={x(active)} x2={x(active)} y1={top} y2={height - bottom} stroke="rgba(255, 255, 255, 0.16)" strokeDasharray="4 4" /><circle cx={x(active)} cy={y(trend[active].conversations)} r="3.5" fill="#4979e0" stroke="#0a0a0a" strokeWidth="2" /></>}
      </>}
    </svg>
    {point && active !== null && <div className="chart-tooltip" style={{ left: `${Math.max(12, Math.min(80, x(active) / width * 100))}%` }}><strong>{dateLabel(point.date, true)}</strong><span><i className="legend-dot purple" />{formatNumber(point.conversations)} conversations</span><span><i className="legend-dot peach" />{formatNumber(point.failures)} flagged</span></div>}
  </div>;
}

function ClusterRow({ cluster, onClick, compact = false }: { cluster: Cluster; onClick: () => void; compact?: boolean }) {
  return <button className={`cluster-row ${compact ? 'cluster-row-compact' : ''}`} onClick={onClick}>
    <span className={`cluster-icon kind-${cluster.kind}`}><TriangleAlert size={17} /></span>
    <span className="cluster-summary"><strong>{cluster.title}</strong><span>{compact ? `${formatNumber(cluster.affected_users)} affected users · ${friendlyKind(cluster.kind)}` : cluster.description}</span></span>
    <span className="cluster-severity"><Severity severity={cluster.severity} /></span>
    <span className="cluster-count"><strong>{formatNumber(cluster.count)}</strong><small>conversations</small></span>
    {!compact && <span className="cluster-share">{cluster.share.toFixed(1)}%</span>}
    {!compact && <span className="cluster-state"><Status status={cluster.status} /></span>}
    <ChevronRight className="row-chevron" size={16} />
  </button>;
}

function ConversationRow({ conversation, onClick, compact = false }: { conversation: Conversation; onClick: () => void; compact?: boolean }) {
  return <button className={`conversation-row ${compact ? 'conversation-row-compact' : ''}`} onClick={onClick}>
    <span className={`conversation-icon ${conversation.status === 'flagged' ? 'flagged' : 'healthy'}`}>
      {conversation.status === 'flagged' ? <TriangleAlert size={15} /> : <MessageSquare size={15} />}
    </span>
    <span className="conversation-summary">
      <strong>{conversation.preview || 'Untitled agent conversation'}</strong>
      <span>
        {shortId(conversation.id)}<i>·</i>{conversation.user_id || 'Anonymous user'}
        {conversation.tags?.length > 0 && <small style={{ marginLeft: 6, color: '#f43f5e' }}>· {conversation.tags.map(friendlyKind).join(', ')}</small>}
      </span>
    </span>
    {!compact && <span className="conversation-model">{conversation.model || 'Default'}</span>}
    {!compact && <span className="conversation-messages">{conversation.message_count} turns</span>}
    <span className="conversation-status"><Status status={conversation.status} /></span>
    <span className="conversation-date">{dateTime(conversation.last_at)}</span>
    <ChevronRight className="row-chevron" size={16} />
  </button>;
}

function AgentPipelineStoryMap({ data, onPage }: { data: Overview; onPage: (page: Page) => void }) {
  const signalCount = data.top_clusters.reduce((sum, c) => sum + c.count, 0);
  return <div className="exec-pipeline">
    <div className="exec-pipeline-header">
      <span className="exec-pipeline-title">
        <Activity size={14} />
        <span>Agent Execution Pipeline · Live Telemetry Flow</span>
      </span>
      <span className="exec-pipeline-mode">
        <span className="pulse-dot" style={{ display: 'inline-block', marginRight: 6 }} />
        {data.analysis_mode === 'rule_based' ? 'Deterministic Engine Active' : data.analysis_mode}
      </span>
    </div>
    <div className="exec-pipeline-grid">
      <button className="exec-pipeline-step" onClick={() => onPage('conversations')}>
        <div className="exec-pipeline-step-top">
          <span>01 · INGEST</span>
          <MessageSquare size={13} />
        </div>
        <strong className="exec-pipeline-count">{formatNumber(data.metrics.conversations)}</strong>
        <span className="exec-pipeline-desc">{formatNumber(data.metrics.messages)} turns buffered</span>
      </button>

      <button className="exec-pipeline-step" onClick={() => onPage('conversations')}>
        <div className="exec-pipeline-step-top">
          <span>02 · SPANS</span>
          <GitBranch size={13} />
        </div>
        <strong className="exec-pipeline-count">{latency(data.metrics.avg_latency_ms)}</strong>
        <span className="exec-pipeline-desc">Avg execution latency</span>
      </button>

      <button className="exec-pipeline-step step-signals" onClick={() => onPage('failures')}>
        <div className="exec-pipeline-step-top">
          <span>03 · SIGNALS</span>
          <TriangleAlert size={13} />
        </div>
        <strong className="exec-pipeline-count">{formatNumber(signalCount)}</strong>
        <span className="exec-pipeline-desc">{data.metrics.failure_rate.toFixed(1)}% flagged turns</span>
      </button>

      <button className="exec-pipeline-step step-clusters" onClick={() => onPage('failures')}>
        <div className="exec-pipeline-step-top">
          <span>04 · CLUSTERS</span>
          <Layers3 size={13} />
        </div>
        <strong className="exec-pipeline-count">{data.top_clusters.length}</strong>
        <span className="exec-pipeline-desc">{formatNumber(data.metrics.affected_users)} affected users</span>
      </button>

      <button className="exec-pipeline-step step-evals" onClick={() => onPage('failures')}>
        <div className="exec-pipeline-step-top">
          <span>05 · REPLAY LAB</span>
          <ShieldCheck size={13} />
        </div>
        <strong className="exec-pipeline-count">Verified</strong>
        <span className="exec-pipeline-desc">Continuous test suites</span>
      </button>
    </div>
  </div>;
}

function OverviewPage({ data, loading, error, retry, range, onPage, onCluster, onConversation, onDemo, demoBusy }: {
  data: Overview | null; loading: boolean; error: string; retry: () => void; range: Range;
  onPage: (page: Page) => void; onCluster: (id: string) => void; onConversation: (id: string) => void;
  onDemo: () => void; demoBusy: boolean;
}) {
  if (loading) return <div className="overview-skeleton"><div className="skeleton-grid">{[0, 1, 2, 3].map(i => <div key={i} className="skeleton skeleton-card" />)}</div><div className="skeleton skeleton-chart" /><div className="skeleton skeleton-chart" /></div>;
  if (error) return <ErrorState message={error} onRetry={retry} />;
  if (!data) return null;
  const metrics = data.metrics;
  if (!metrics.conversations) return <div className="first-conversation"><div className="panel"><EmptyState icon={Activity} title="Your first insight starts with a conversation." description="Connect an agent to this project. Tervik will organize its conversations and surface signals that deserve a closer look.">
    <button className="button button-primary" onClick={() => onPage('integration')}><Zap size={16} />Connect your agent<ArrowRight size={16} /></button>
    <button className="button button-secondary" disabled={demoBusy} onClick={onDemo}>{demoBusy ? <LoaderCircle size={15} className="spin" /> : <Layers3 size={16} />}Explore sample workspace</button>
  </EmptyState></div><div className="getting-started-cards"><GuideCard icon={MessageSquare} title="Follow every conversation" text="See the messages, tool calls, latency, and cost in one place." /><GuideCard icon={TriangleAlert} title="Find the friction" text="Group corrections, repeated requests, frustration, and tool errors." /><GuideCard icon={GitBranch} title="Review the next step" text="Investigate the evidence and turn it into a fix you can validate." /></div></div>;
  return <>
    <AgentPipelineStoryMap data={data} onPage={onPage} />

    <div className="metric-grid">
      <Metric label="Conversations" value={formatNumber(metrics.conversations)} icon={MessageSquare} detail={`${formatNumber(metrics.messages)} messages received`} />
      <Metric label="Flagged conversations" value={`${metrics.failure_rate.toFixed(1)}%`} icon={TriangleAlert} detail="Signals to investigate" accent />
      <Metric label="Affected users" value={formatNumber(metrics.affected_users)} icon={Users} detail="Users with flagged conversations" />
      <Metric label="Average latency" value={latency(metrics.avg_latency_ms)} icon={Clock3} detail={`${money(metrics.cost_usd)} reported total cost`} />
    </div>
    <section className="panel activity-panel"><div className="panel-heading"><div><h2>Conversation activity</h2><p>Every interaction. A clearer picture.</p></div><div className="chart-legend"><span><i className="legend-dot purple" />Conversations</span><span><i className="legend-dot peach" />Flagged</span></div></div><TrendChart trend={data.trend} range={range} />
      <div className="chart-footer"><span><span className="pulse-dot" />{rangeLabels[range]}</span><span>Based on received events</span></div>
    </section>
    <div className="overview-lower"><section className="panel cluster-panel"><div className="panel-heading"><div className="heading-with-count"><h2>What needs attention</h2><span className="count-badge">{data.top_clusters.length}</span></div><button className="text-button" onClick={() => onPage('failures')}>View all<ArrowRight size={14} /></button></div>
      {data.top_clusters.length ? <div>{data.top_clusters.slice(0, 5).map(cluster => <ClusterRow key={cluster.id} cluster={cluster} compact onClick={() => onCluster(cluster.id)} />)}</div> : <EmptyState icon={CheckCheck} title="No signals in this period" description="Received conversations haven’t matched the current triage rules." />}
      <div className="panel-note"><CircleHelp size={14} />Clusters use rule-based signals. Review the evidence before acting.</div>
    </section><section className="panel recent-panel"><div className="panel-heading"><h2>Recent conversations</h2><button className="text-button" onClick={() => onPage('conversations')}>View all<ArrowRight size={14} /></button></div>
      {data.recent_conversations.length ? data.recent_conversations.slice(0, 5).map(conversation => <ConversationRow key={conversation.id} conversation={conversation} compact onClick={() => onConversation(conversation.id)} />) : <EmptyState title="No recent conversations" description="New conversations will appear here." />}
    </section></div>
    <div className="connect-strip"><span className="strip-icon"><Terminal size={20} /></span><div><strong>Better agents start with visibility.</strong><p>Add Tervik to your next agent with one skill.</p></div><button className="button button-secondary" onClick={() => onPage('integration')}>View integration<ArrowUpRight size={15} /></button></div>
  </>;
}

function Metric({ label, value, detail, icon: Icon, accent = false }: { label: string; value: string; detail: string; icon: LucideIcon; accent?: boolean }) {
  return <div className={`metric-card ${accent ? 'metric-accent' : ''}`}><div className="metric-label">{label}<Icon size={17} /></div><strong className="metric-value">{value}</strong><span className="metric-detail">{detail}</span></div>;
}
function GuideCard({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return <div className="guide-card"><Icon size={21} /><h3>{title}</h3><p>{text}</p></div>;
}

function RulesManager({ projectId, refresh }: { projectId: string; refresh: number }) {
  const resource = useResource<BehaviorRule[]>(`/api/projects/${encodeURIComponent(projectId)}/rules`, refresh);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<'forbidden_phrase' | 'required_tool'>('forbidden_phrase');
  const [pattern, setPattern] = useState('');
  const [tool, setTool] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      await request('/api/projects/' + encodeURIComponent(projectId) + '/rules', {
        method: 'POST', body: JSON.stringify(kind === 'forbidden_phrase' ? { name, kind, pattern } : { name, kind, tool }),
      });
      setName(''); setPattern(''); setTool(''); resource.retry();
    } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  const mutate = async (action: () => Promise<unknown>) => {
    setError('');
    try { await action(); resource.retry(); } catch (cause) { setError((cause as Error).message); }
  };
  return <section className="panel"><div className="panel-heading"><div><h2>Behavior rules</h2><p>Your definitions. Violations cite the rule and the matching record.</p></div></div>
    {resource.loading ? <Loading label="Loading rules" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> :
      <div>{resource.data?.length ? resource.data.map(rule => <div key={rule.id} className="related-conversation"><ShieldCheck size={15} /><span><strong>{rule.name}</strong><small>{rule.kind === 'forbidden_phrase' ? `forbidden phrase: ${rule.pattern}` : `required tool: ${rule.tool}`} · {rule.enabled ? 'enabled' : 'disabled'} · v{rule.version}</small></span><button className="text-button" onClick={() => mutate(() => request(`/api/rules/${encodeURIComponent(rule.id)}`, { method: 'PATCH', body: JSON.stringify({ enabled: !rule.enabled }) }))}>{rule.enabled ? 'Disable' : 'Enable'}</button><button className="text-button" onClick={() => mutate(() => request(`/api/rules/${encodeURIComponent(rule.id)}`, { method: 'DELETE' }))}>Delete</button></div>) : <p className="muted">No behavior rules yet. Add one to catch project-specific failures.</p>}</div>}
    <form className="modal-body" onSubmit={submit}><label className="field-label" htmlFor="rule-name">Rule name</label><input id="rule-name" className="text-field" value={name} onChange={event => setName(event.target.value)} required maxLength={120} placeholder="e.g. Never promise refunds" /><label className="field-label" htmlFor="rule-kind">Rule kind</label><select id="rule-kind" className="text-field" value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="forbidden_phrase">Forbidden phrase (regex on assistant messages)</option><option value="required_tool">Required tool (must succeed per conversation)</option></select>{kind === 'forbidden_phrase' ? <><label className="field-label" htmlFor="rule-pattern">Pattern</label><input id="rule-pattern" className="text-field" value={pattern} onChange={event => setPattern(event.target.value)} required maxLength={500} placeholder="e.g. guarantee\w*" /></> : <><label className="field-label" htmlFor="rule-tool">Tool name</label><input id="rule-tool" className="text-field" value={tool} onChange={event => setTool(event.target.value)} required maxLength={200} placeholder="e.g. lookup_policy" /></>}{error && <p className="inline-error">{error}</p>}<div className="modal-actions"><button type="submit" className="button button-primary" disabled={busy || !name.trim()}>{busy ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />}Add rule</button></div></form>
  </section>;
}

function AlertsPanel({ projectId, refresh }: { projectId: string; refresh: number }) {
  const rules = useResource<AlertRule[]>(`/api/projects/${encodeURIComponent(projectId)}/alerts`, refresh);
  const deliveries = useResource<Delivery[]>(`/api/projects/${encodeURIComponent(projectId)}/deliveries`, refresh);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<'threshold' | 'trend' | 'summary'>('threshold');
  const [signalKind, setSignalKind] = useState('');
  const [threshold, setThreshold] = useState('5');
  const [channelType, setChannelType] = useState<'webhook' | 'email'>('webhook');
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await work(); rules.retry(); deliveries.retry(); } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  return <section className="panel"><div className="panel-heading"><div><h2>Alerts</h2><p>Threshold, trend, and daily-summary rules. A qualifying finding sends once per cooldown window.</p></div><button className="button button-secondary" disabled={busy} onClick={() => act(() => request(`/api/projects/${encodeURIComponent(projectId)}/alerts/evaluate`, { method: 'POST' }))}>Evaluate now</button></div>
    {error && <p className="inline-error">{error}</p>}
    {rules.loading ? <Loading label="Loading alerts" /> : rules.error ? <ErrorState message={rules.error} onRetry={rules.retry} /> :
      <div>{rules.data?.length ? rules.data.map(rule => <div key={rule.id} className="related-conversation"><TriangleAlert size={15} /><span><strong>{rule.name}</strong><small>{rule.kind}{rule.signal_kind ? ` · ${rule.signal_kind}` : ''} · threshold {rule.threshold} · {rule.window_hours}h window · {rule.state}{rule.enabled ? '' : ' · disabled'}</small></span><button className="text-button" onClick={() => act(() => request(`/api/alerts/${encodeURIComponent(rule.id)}`, { method: 'PATCH', body: JSON.stringify({ enabled: !rule.enabled }) }))}>{rule.enabled ? 'Disable' : 'Enable'}</button><button className="text-button" onClick={() => act(() => request(`/api/alerts/${encodeURIComponent(rule.id)}`, { method: 'DELETE' }))}>Delete</button></div>) : <p className="muted">No alert rules yet. Add one to get notified when failures spike.</p>}</div>}
    <form className="modal-body" onSubmit={event => { event.preventDefault(); if (!name.trim() || !target.trim()) return; act(() => request(`/api/projects/${encodeURIComponent(projectId)}/alerts`, { method: 'POST', body: JSON.stringify({ name: name.trim(), kind, signal_kind: signalKind.trim() || null, threshold: Number(threshold) || 1, channels: [{ type: channelType, target: target.trim() }] }) })).then(() => { setName(''); setSignalKind(''); setTarget(''); }); }}><label className="field-label" htmlFor="alert-name">Rule name</label><input id="alert-name" className="text-field" value={name} onChange={event => setName(event.target.value)} required maxLength={120} placeholder="e.g. Frustration spike" /><div className="modal-actions" style={{ justifyContent: 'flex-start', gap: 8 }}><select aria-label="Alert kind" className="text-field" value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="threshold">Threshold</option><option value="trend">Trend</option><option value="summary">Daily summary</option></select><input aria-label="Signal kind (optional)" className="text-field" value={signalKind} onChange={event => setSignalKind(event.target.value)} placeholder="signal kind, e.g. frustration" /><input aria-label="Threshold" className="text-field" value={threshold} onChange={event => setThreshold(event.target.value)} inputMode="decimal" placeholder="5" /></div><label className="field-label" htmlFor="alert-target">{channelType === 'webhook' ? 'Slack-compatible webhook URL' : 'Email address'}</label><div className="modal-actions" style={{ justifyContent: 'flex-start', gap: 8 }}><select aria-label="Channel type" className="text-field" value={channelType} onChange={event => setChannelType(event.target.value as typeof channelType)}><option value="webhook">Webhook</option><option value="email">Email</option></select><input id="alert-target" className="text-field" value={target} onChange={event => setTarget(event.target.value)} required maxLength={500} placeholder={channelType === 'webhook' ? 'https://hooks.slack.com/...' : 'team@example.com'} /></div><div className="modal-actions"><button type="submit" className="button button-primary" disabled={busy}><Plus size={16} />Add alert</button></div></form>
    <div className="detail-section"><div className="section-label"><Zap size={15} />Recent deliveries<span>{deliveries.data?.length || 0}</span></div>
      {deliveries.data?.map(delivery => <div key={delivery.id} className="related-conversation"><span className={`span-kind ${delivery.state === 'sent' ? '' : 'span-error'}`}>{delivery.state === 'sent' ? <Check size={15} /> : <TriangleAlert size={15} />}</span><span><strong>{delivery.title}</strong><small>{delivery.channel_type} · {delivery.attempts} attempts{delivery.error_code ? ` · ${delivery.error_code}` : ''} · {dateTime(delivery.created_at)}</small></span>{delivery.state !== 'sent' && <button className="text-button" onClick={() => act(() => request(`/api/deliveries/${encodeURIComponent(delivery.id)}/replay`, { method: 'POST' }))}>Retry</button>}</div>)}
    </div>
  </section>;
}

function EvaluationsPanel({ projectId, refresh }: { projectId: string; refresh: number }) {
  const datasets = useResource<EvalDataset[]>(`/api/projects/${encodeURIComponent(projectId)}/datasets`, refresh);
  const [runs, setRuns] = useState<Record<string, EvalRun[]>>({});
  const [name, setName] = useState('');
  const [kinds, setKinds] = useState('unsupported_claim,tool_error');
  const [baseline, setBaseline] = useState('{"name":"baseline","version":"v1","tools_plan":[],"response_template":"We got your message about {input}."}');
  const [candidate, setCandidate] = useState('{"name":"candidate","version":"v2","tools_plan":[],"response_template":"Checked: {input}."}');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await work(); datasets.retry(); } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  const loadRuns = async (id: string) => {
    try {
      const rows = await request<EvalRun[]>(`/api/datasets/${encodeURIComponent(id)}/runs`);
      setRuns(prev => ({ ...prev, [id]: rows }));
    } catch (cause) { setError((cause as Error).message); }
  };
  const runComparison = async (id: string) => {
    let base, cand;
    try { base = JSON.parse(baseline); cand = JSON.parse(candidate); }
    catch { setError('Baseline/candidate must be valid JSON agent descriptors.'); return; }
    await act(async () => {
      await request(`/api/datasets/${encodeURIComponent(id)}/runs`, { method: 'POST', body: JSON.stringify({ baseline: base, candidate: cand, repeats: 2 }) });
      await loadRuns(id);
    });
  };
  return <section className="panel"><div className="panel-heading"><div><h2>Evaluations</h2><p>Datasets from production findings, reviewed before running. Replay compares candidates without touching live systems.</p></div></div>
    {error && <p className="inline-error">{error}</p>}
    {datasets.loading ? <Loading label="Loading datasets" /> : datasets.error ? <ErrorState message={datasets.error} onRetry={datasets.retry} /> :
      <div>{datasets.data?.length ? datasets.data.map(dataset => <div key={dataset.id}><div className="related-conversation"><Layers3 size={15} /><span><strong>{dataset.name}</strong><small>{dataset.case_count} cases · {dataset.status} · v{dataset.version}</small></span>{dataset.status === 'draft' && <button className="text-button" onClick={() => act(() => request(`/api/datasets/${encodeURIComponent(dataset.id)}`, { method: 'PATCH', body: JSON.stringify({ status: 'reviewed' }) }))}>Mark reviewed</button>}{dataset.status === 'reviewed' && <button className="text-button" onClick={() => act(() => request(`/api/datasets/${encodeURIComponent(dataset.id)}`, { method: 'PATCH', body: JSON.stringify({ status: 'approved' }) }))}>Approve</button>}<button className="text-button" onClick={() => loadRuns(dataset.id)}>Runs</button></div>
        {(runs[dataset.id] || []).map(run => <div key={run.id} className="evidence-card"><span className="evidence-marker">{run.results.verdict}</span><blockquote>{run.baseline.name} {run.results.baseline_pass}/{run.results.cases} → {run.candidate.name} {run.results.candidate_pass}/{run.results.cases}{run.results.reproducible ? ' · reproducible' : ' · UNSTABLE'}</blockquote><p>Fixed: {run.results.fixed.join(', ') || '—'} · Regressed: {run.results.regressed.join(', ') || '—'} · violations {run.results.baseline_violations} → {run.results.candidate_violations}</p></div>)}
        {dataset.status !== 'draft' && <div className="modal-body"><label className="field-label">Baseline JSON</label><textarea className="text-field" rows={2} value={baseline} onChange={event => setBaseline(event.target.value)} /><label className="field-label">Candidate JSON</label><textarea className="text-field" rows={2} value={candidate} onChange={event => setCandidate(event.target.value)} /><div className="modal-actions"><button className="button button-primary" disabled={busy} onClick={() => runComparison(dataset.id)}>Run comparison ×2</button></div></div>}
      </div>) : <p className="muted">No evaluation datasets yet. Build one from production findings below.</p>}</div>}
    <form className="modal-body" onSubmit={event => { event.preventDefault(); if (!name.trim()) return; act(() => request(`/api/projects/${encodeURIComponent(projectId)}/datasets/from-findings`, { method: 'POST', body: JSON.stringify({ name: name.trim(), signal_kinds: kinds.split(',').map(s => s.trim()).filter(Boolean), include_controls: true, limit: 20 }) })).then(() => setName('')); }}><label className="field-label" htmlFor="dataset-name">Build from findings</label><input id="dataset-name" className="text-field" value={name} onChange={event => setName(event.target.value)} required maxLength={120} placeholder="e.g. Refund regressions" /><input aria-label="Signal kinds" className="text-field" value={kinds} onChange={event => setKinds(event.target.value)} placeholder="unsupported_claim,tool_error" /><div className="modal-actions"><button type="submit" className="button button-primary" disabled={busy}><Plus size={16} />Build dataset</button></div></form>
  </section>;
}

const NEXT_STATE: Record<string, string[]> = {
  proposed: ['investigating'],
  investigating: ['candidate_ready'],
  candidate_ready: ['evaluating'],
  evaluating: ['awaiting_approval'],
  awaiting_approval: ['deployed'],
  deployed: ['monitoring', 'rolled_back'],
  monitoring: ['resolved', 'rolled_back'],
};

function ImprovementsPanel({ projectId, refresh }: { projectId: string; refresh: number }) {
  const improvements = useResource<Improvement[]>(`/api/projects/${encodeURIComponent(projectId)}/improvements`, refresh);
  const [selected, setSelected] = useState<string | null>(null);
  const [kind, setKind] = useState('unsupported_claim');
  const [tool, setTool] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await work(); improvements.retry(); } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  return <section className="panel"><div className="panel-heading"><div><h2>Suggested fixes</h2><p>Evidence-backed proposals. Nothing deploys before approval, and rollback restores the prior version.</p></div></div>
    {error && <p className="inline-error">{error}</p>}
    {improvements.loading ? <Loading label="Loading improvements" /> : improvements.error ? <ErrorState message={improvements.error} onRetry={improvements.retry} /> :
      <div>{improvements.data?.length ? improvements.data.map(item => <div key={item.id} className="related-conversation"><GitBranch size={15} /><span><strong>{item.title}</strong><small>{item.signal_kind || 'general'} · {item.state}{item.eval_run_id ? ' · evaluated' : ' · unevaluated'}</small></span><button className="text-button" onClick={() => setSelected(item.id)}>Open<ChevronRight size={15} /></button></div>) : <p className="muted">No suggested fixes yet. Propose one from a failure signal below.</p>}</div>}
    <form className="modal-body" onSubmit={event => { event.preventDefault(); act(() => request(`/api/projects/${encodeURIComponent(projectId)}/improvements`, { method: 'POST', body: JSON.stringify({ signal_kind: kind, tool: tool.trim() || null }) })); }}><label className="field-label" htmlFor="imp-kind">Signal kind</label><input id="imp-kind" className="text-field" value={kind} onChange={event => setKind(event.target.value)} required maxLength={40} /><label className="field-label" htmlFor="imp-tool">Tool (optional)</label><input id="imp-tool" className="text-field" value={tool} onChange={event => setTool(event.target.value)} maxLength={200} placeholder="e.g. refund_tool" /><div className="modal-actions"><button type="submit" className="button button-primary" disabled={busy}><Plus size={16} />Propose fix</button></div></form>
    {selected && <ImprovementDrawer id={selected} onClose={() => setSelected(null)} onChanged={() => improvements.retry()} />}
  </section>;
}

function ImprovementDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const resource = useResource<Improvement & { prompts: { id: string; path: string; version: number; status: string; content: string }[] }>(`/api/improvements/${encodeURIComponent(id)}`);
  const [evalRunId, setEvalRunId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const item = resource.data;
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await work(); resource.retry(); onChanged(); } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  return <Modal title="Improvement review" onClose={onClose} sheet>
    {resource.loading ? <Loading label="Loading improvement" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> : item && <div className="drawer-content">
      <div className="drawer-eyebrow"><Status status={item.state === 'resolved' ? 'healthy' : 'flagged'} /><span>{item.signal_kind || 'general'}</span><span>{item.state}</span></div>
      <h2 className="drawer-title">{item.title}</h2>
      <p className="drawer-description">{item.cause}</p>
      <p className="muted">Uncertainty: {item.uncertainty}</p>
      {item.evidence.length > 0 && <div className="detail-section"><div className="section-label"><MessageSquare size={15} />Evidence<span>{item.evidence.length}</span></div>{item.evidence.map(evidence => <div className="evidence-card" key={evidence.event_id}><blockquote>“{evidence.content}”</blockquote></div>)}</div>}
      <div className="detail-section"><div className="section-label"><Code2 size={15} />Candidate diff</div><pre className="code-block"><code>{item.candidate_diff || 'No diff yet.'}</code></pre></div>
      {item.prompts.map(prompt => <p key={prompt.id} className="muted">{prompt.path} v{prompt.version} · {prompt.status}</p>)}
      {item.measurements && Object.keys(item.measurements).length > 0 && <div className="detail-section"><div className="section-label"><Activity size={15} />Post-deployment measurements</div><pre className="code-block"><code>{JSON.stringify(item.measurements, null, 2)}</code></pre></div>}
      {error && <p className="inline-error">{error}</p>}
      <div className="detail-section"><div className="section-label"><Zap size={15} />Evaluate</div><div className="key-box"><input className="text-field" aria-label="Evaluation run ID" placeholder="Eval run ID..." value={evalRunId} onChange={event => setEvalRunId(event.target.value)} /><button className="button button-secondary" disabled={busy || !evalRunId.trim()} onClick={() => act(() => request(`/api/improvements/${encodeURIComponent(item.id)}/eval`, { method: 'POST', body: JSON.stringify({ eval_run_id: evalRunId.trim() }) }))}>Attach</button></div><p className="muted">Run comparisons in Evaluations, then attach the verifying run here.</p></div>
      <div className="drawer-bottom"><span>Lifecycle: proposed → investigating → candidate → evaluating → approval → deployed → monitoring → resolved</span></div>
      <div className="modal-actions" style={{ flexWrap: 'wrap', gap: 8 }}>{(NEXT_STATE[item.state] || []).map(next => <button key={next} className={`button ${next === 'deployed' ? 'button-primary' : 'button-secondary'}`} disabled={busy} onClick={() => act(() => request(`/api/improvements/${encodeURIComponent(item.id)}/transition`, { method: 'POST', body: JSON.stringify({ to: next }) }))}>{next.replace('_', ' ')}</button>)}</div>
    </div>}
  </Modal>;
}

function FailuresPage({ projectId, range, refresh, onSelect }: { projectId: string; range: Range; refresh: number; onSelect: (id: string) => void }) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => { const timer = window.setTimeout(() => setDebounced(search), 250); return () => window.clearTimeout(timer); }, [search]);
  const resource = useResource<Cluster[]>(`/api/clusters${query({ project_id: projectId, range, search: debounced, status })}`, refresh);
  return <>
    <div className="context-banner"><span className="context-icon"><Sparkles size={18} /></span><div><strong>Find the patterns behind the friction.</strong><span>Similar failure signals are grouped together, with the conversations that explain them.</span></div><span className="subtle-pill">Rule-based triage</span></div>
    <section className="panel"><div className="list-toolbar"><div className="tab-switch" aria-label="Cluster status">{[['', 'All clusters'], ['open', 'Open'], ['resolved', 'Resolved']].map(([value, label]) => <button key={value} className={status === value ? 'active' : ''} onClick={() => setStatus(value)}>{label}</button>)}</div><label className="search-input"><Search size={16} /><input aria-label="Search failure clusters" placeholder="Search clusters..." value={search} onChange={event => setSearch(event.target.value)} />{search && <button aria-label="Clear search" onClick={() => setSearch('')}><X size={14} /></button>}</label></div>
      <div className="cluster-table-head"><span>Failure pattern</span><span>Severity</span><span>Conversations</span><span>Share</span><span>Status</span><span /></div>
      {resource.loading ? <Loading label="Finding patterns" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> : resource.data?.length ? resource.data.map(cluster => <ClusterRow key={cluster.id} cluster={cluster} onClick={() => onSelect(cluster.id)} />) : <EmptyState icon={search ? Search : CheckCheck} title={search ? 'No matching clusters' : status === 'resolved' ? 'No resolved clusters yet' : 'No failure signals in this period'} description={search ? 'Try a different search or clear your filters.' : status === 'resolved' ? 'Clusters you mark as resolved will appear here.' : 'Choose another date range or send conversations from your agent.'} />}
      <div className="list-footer"><span>{formatNumber(resource.data?.length || 0)} {resource.data?.length === 1 ? 'cluster' : 'clusters'}</span><span><ShieldCheck size={13} />Resolving a cluster records your review. It doesn’t change your agent.</span></div>
    </section>
    <AlertsPanel projectId={projectId} refresh={refresh} />
    <ImprovementsPanel projectId={projectId} refresh={refresh} />
    <EvaluationsPanel projectId={projectId} refresh={refresh} />
    <RulesManager projectId={projectId} refresh={refresh} />
  </>;
}

function DiscoveryPage({ projectId, range, refresh, onConversation }: { projectId: string; range: Range; refresh: number; onConversation: (id: string) => void }) {
  const resource = useResource<Discovery>(`/api/projects/${encodeURIComponent(projectId)}/discovery?range=${range}`, refresh);
  const intents = useResource<DiscoveryIntent[]>(`/api/projects/${encodeURIComponent(projectId)}/intents`, refresh);
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<string[]>([]);
  const [label, setLabel] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [intentName, setIntentName] = useState('');
  const [intentExamples, setIntentExamples] = useState('');
  const data = resource.data;
  const cluster = data?.clusters.find(item => item.id === selected) || null;
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await work(); resource.retry(); intents.retry(); setChecked([]); setLabel(''); }
    catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  const toggle = (id: string) => setChecked(items => items.includes(id) ? items.filter(item => item !== id) : [...items, id]);
  return <>
    <div className="context-banner"><span className="context-icon"><Sparkles size={18} /></span><div><strong>What are users trying to accomplish?</strong><span>Recurring topics group here with the conversations that explain them. Messages, conversations, and users are different counts.</span></div><span className="subtle-pill">Discovery {data?.clusters[0]?.detector_version || '6.0.0'}</span></div>
    {resource.loading ? <Loading label="Discovering topics" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> : data && <>
      <div className="metric-grid">
        <Metric label="Grouped conversations" value={`${formatNumber(data.coverage.clustered)} / ${formatNumber(data.coverage.conversations_analyzed)}`} icon={Layers3} detail={`${formatNumber(data.coverage.messages_total)} messages · ${formatNumber(data.coverage.users_total)} users`} />
        <Metric label="Topics" value={formatNumber(data.clusters.length)} icon={MessageSquare} detail={`${formatNumber(data.coverage.unassigned)} unassigned conversations`} />
        <Metric label="Intents matched" value={formatNumber(data.intents.reduce((sum, item) => sum + item.conversations, 0))} icon={Users} detail={`${data.intents.length} configured intents`} />
      </div>
      <section className="panel"><div className="panel-heading"><div><h2>Recurring topics</h2><p>Select topics to merge, or open one to rename, split, or dismiss. Edits never touch the underlying conversations.</p></div>{checked.length >= 2 && <div><input className="text-field" aria-label="Merged topic label" placeholder="Merged topic label..." value={label} onChange={event => setLabel(event.target.value)} /><button className="button button-primary" disabled={busy || !label.trim()} onClick={() => act(() => request(`/api/projects/${encodeURIComponent(projectId)}/discovery/merge`, { method: 'POST', body: JSON.stringify({ source_ids: checked, label: label.trim() }) }))}>Merge {checked.length}</button></div>}</div>
        {error && <p className="inline-error">{error}</p>}
        {data.clusters.length ? data.clusters.map(item => <div key={item.id} className="related-conversation"><input type="checkbox" aria-label={`Select ${item.label}`} checked={checked.includes(item.id)} onChange={() => toggle(item.id)} /><MessageSquare size={15} /><span><strong>{item.label}</strong><small>{formatNumber(item.count)} conversations · {formatNumber(item.affected_users)} users · {item.status}</small></span><button className="text-button" onClick={() => setSelected(item.id)}>Open<ChevronRight size={15} /></button></div>) : <EmptyState icon={Sparkles} title="No recurring topics yet" description="Send more conversations and related phrasings will group here." />}
        <div className="list-footer"><span>Coverage: {formatNumber(data.coverage.clustered)} of {formatNumber(data.coverage.conversations_analyzed)} analyzed conversations grouped</span><span><ShieldCheck size={13} />Dismissing hides a topic. Conversations stay intact.</span></div>
      </section>
      <section className="panel"><div className="panel-heading"><div><h2>Configured intents</h2><p>Intents match before traffic accumulates. Examples define each intent.</p></div></div>
        {intents.data?.map(intent => <div key={intent.id} className="related-conversation"><MessageSquare size={15} /><span><strong>{intent.name}</strong><small>{intent.examples.length} examples · {(data.intents.find(i => i.intent_id === intent.id)?.conversations || 0)} conversations · {intent.enabled ? 'enabled' : 'disabled'}</small></span><button className="text-button" onClick={() => act(() => request(`/api/intents/${encodeURIComponent(intent.id)}`, { method: 'PATCH', body: JSON.stringify({ enabled: !intent.enabled }) }))}>{intent.enabled ? 'Disable' : 'Enable'}</button><button className="text-button" onClick={() => act(() => request(`/api/intents/${encodeURIComponent(intent.id)}`, { method: 'DELETE' }))}>Delete</button></div>)}
        <form className="modal-body" onSubmit={event => { event.preventDefault(); if (!intentName.trim() || !intentExamples.trim()) return; act(() => request(`/api/projects/${encodeURIComponent(projectId)}/intents`, { method: 'POST', body: JSON.stringify({ name: intentName.trim(), examples: intentExamples.split('\n').map(s => s.trim()).filter(Boolean) }) })).then(() => { setIntentName(''); setIntentExamples(''); }); }}><label className="field-label" htmlFor="intent-name">Intent name</label><input id="intent-name" className="text-field" value={intentName} onChange={event => setIntentName(event.target.value)} required maxLength={120} placeholder="e.g. Refund request" /><label className="field-label" htmlFor="intent-examples">Examples (one per line)</label><textarea id="intent-examples" className="text-field" value={intentExamples} onChange={event => setIntentExamples(event.target.value)} rows={3} placeholder={"get a refund\nrefund my order"} /><div className="modal-actions"><button type="submit" className="button button-primary" disabled={busy}><Plus size={16} />Add intent</button></div></form>
      </section>
    </>}
    {cluster && <DiscoveryDrawer cluster={cluster} projectId={projectId} onClose={() => setSelected(null)} onConversation={onConversation} onChanged={() => { resource.retry(); }} />}
  </>;
}

function DiscoveryDrawer({ cluster, projectId, onClose, onConversation, onChanged }: { cluster: Discovery['clusters'][number]; projectId: string; onClose: () => void; onConversation: (id: string) => void; onChanged: () => void }) {
  const [rename, setRename] = useState(cluster.label);
  const [split, setSplit] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const act = async (work: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await work(); onChanged(); } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  return <Modal title="Topic investigation" onClose={onClose} sheet>
    <div className="drawer-content">
      <div className="drawer-eyebrow"><Status status="open" /><span>{formatNumber(cluster.count)} conversations</span></div>
      <h2 className="drawer-title">{cluster.label}</h2>
      <div className="detail-section"><div className="section-label"><MessageSquare size={15} />Evidence<span>{cluster.evidence.length}</span></div>
        {cluster.evidence.map((item, index) => <div className="evidence-card" key={`${item.conversation_id}-${index}`}><span className="evidence-marker">{String(index + 1).padStart(2, '0')}</span><blockquote>“{item.excerpt}”</blockquote><p><TriangleAlert size={13} />{item.reason}</p><button className="text-button" onClick={() => onConversation(item.conversation_id)}>Open conversation<ArrowUpRight size={14} /></button></div>)}
      </div>
      <div className="detail-section"><div className="section-label"><Layers3 size={15} />Members<span>{cluster.members.length}</span></div>
        {cluster.members.map(id => <div key={id} className="related-conversation"><input type="checkbox" aria-label={`Split ${shortId(id)}`} checked={split.includes(id)} onChange={() => setSplit(items => items.includes(id) ? items.filter(item => item !== id) : [...items, id])} /><MessageSquare size={15} /><span><strong>{shortId(id)}</strong></span><button className="text-button" onClick={() => onConversation(id)}>Open<ChevronRight size={15} /></button></div>)}
      </div>
      {error && <p className="inline-error">{error}</p>}
      <div className="detail-section"><div className="section-label"><Settings2 size={15} />Manage</div>
        <label className="field-label" htmlFor="discovery-rename">Rename (evidence untouched)</label>
        <div className="key-box"><input id="discovery-rename" className="text-field" value={rename} onChange={event => setRename(event.target.value)} maxLength={200} /><button className="button button-secondary" disabled={busy || !rename.trim()} onClick={() => act(() => request(`/api/discovery/${encodeURIComponent(cluster.id)}/rename`, { method: 'POST', body: JSON.stringify({ label: rename.trim() }) }))}>Save</button></div>
        <div className="drawer-bottom"><button className="button button-secondary" disabled={busy} onClick={() => act(() => request(`/api/discovery/${encodeURIComponent(cluster.id)}`, { method: 'PATCH', body: JSON.stringify({ status: 'dismissed' }) }).then(onClose))}>Dismiss topic</button>
        <button className="button button-primary" disabled={busy || split.length === 0 || split.length >= cluster.members.length} onClick={() => act(() => request(`/api/projects/${encodeURIComponent(projectId)}/discovery/split`, { method: 'POST', body: JSON.stringify({ label: `${cluster.label} (split)`, member_conversation_ids: split }) }).then(onClose))}>Split selection</button></div>
      </div>
    </div>
  </Modal>;
}

function ConversationsPage({ projectId, range, refresh, onSelect }: { projectId: string; range: Range; refresh: number; onSelect: (id: string) => void }) {
  const [search, setSearch] = useState('');
  const [flagged, setFlagged] = useState(false);
  const [debounced, setDebounced] = useState('');
  useEffect(() => { const timer = window.setTimeout(() => setDebounced(search), 250); return () => window.clearTimeout(timer); }, [search]);
  const resource = useResource<Conversation[]>(`/api/conversations${query({ project_id: projectId, range, search: debounced, flagged: flagged ? 'true' : undefined })}`, refresh);
  return <section className="panel"><div className="list-toolbar"><label className="search-input wide-search"><Search size={16} /><input aria-label="Search conversations" placeholder="Search messages, users, or conversation IDs..." value={search} onChange={event => setSearch(event.target.value)} />{search && <button aria-label="Clear search" onClick={() => setSearch('')}><X size={14} /></button>}</label><button className={`filter-button ${flagged ? 'selected' : ''}`} onClick={() => setFlagged(!flagged)} aria-pressed={flagged}><Filter size={15} />Flagged only{flagged && <Check size={13} />}</button></div>
    <div className="conversation-table-head"><span>Conversation</span><span>Model</span><span>Messages</span><span>Status</span><span>Last activity</span><span /></div>
    {resource.loading ? <Loading label="Loading conversations" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> : resource.data?.length ? resource.data.map(conversation => <ConversationRow key={conversation.id} conversation={conversation} onClick={() => onSelect(conversation.id)} />) : <EmptyState icon={search ? Search : MessageSquare} title={search || flagged ? 'No matching conversations' : 'Your conversations will appear here'} description={search || flagged ? 'Try clearing your search or the flagged filter.' : 'Install the Tervik skill and send your first events to start exploring.'} />}
    <div className="list-footer"><span>{formatNumber(resource.data?.length || 0)} conversations</span><span>Click a conversation to explore its messages and trace.</span></div>
  </section>;
}

function ClusterDrawer({ id, range, onClose, onConversation, onChanged }: { id: string; range: Range; onClose: () => void; onConversation: (id: string) => void; onChanged: () => void }) {
  const resource = useResource<ClusterDetail>(`/api/clusters/${encodeURIComponent(id)}?range=${range}`);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [buildingEval, setBuildingEval] = useState(false);
  const [evalSuccess, setEvalSuccess] = useState('');
  const [evalError, setEvalError] = useState('');
  const cluster = resource.data;
  return <Modal title="Cluster investigation" onClose={onClose} sheet>
    {resource.loading ? <Loading label="Loading evidence" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> : cluster && <div className="drawer-content">
      <div className="drawer-eyebrow"><Severity severity={cluster.severity} /><Status status={cluster.status} /><span>{friendlyKind(cluster.kind)}</span></div><h2 className="drawer-title">{cluster.title}</h2><p className="drawer-description">{cluster.description}</p>
      <div className="drawer-stats"><div><strong>{formatNumber(cluster.count)}</strong><span>Conversations</span></div><div><strong>{formatNumber(cluster.affected_users)}</strong><span>Affected users</span></div><div><strong>{cluster.share.toFixed(1)}%</strong><span>Conversation share</span></div></div>
      
      {/* Closed-loop Replay Suite Generator */}
      <div className="cluster-eval-builder">
        <div className="cluster-eval-builder-head">
          <h4>Turn into Evaluation Suite</h4>
          <span className="subtle-pill"><Sparkles size={12} style={{ marginRight: 4 }} />Replay Lab</span>
        </div>
        <p>Convert this production failure pattern into an automated regression dataset to verify fixes before shipping.</p>
        <button className="button button-primary" disabled={buildingEval} onClick={async () => {
          setBuildingEval(true); setEvalError(''); setEvalSuccess('');
          try {
            const res = await request<{ id: string; name: string }>(`/api/projects/${encodeURIComponent(cluster.project_id)}/datasets/from-findings`, {
              method: 'POST',
              body: JSON.stringify({
                name: `Regression suite: ${cluster.title.slice(0, 48)}`,
                signal_kinds: [cluster.kind],
                include_controls: true,
                limit: 15,
              }),
            });
            setEvalSuccess(`Created dataset "${res.name}". Open Evaluations to replay baseline vs candidate.`);
          } catch (e) {
            setEvalError((e as Error).message);
          } finally {
            setBuildingEval(false);
          }
        }}>
          {buildingEval ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />}
          <span>Generate Replay Dataset</span>
        </button>
        {evalSuccess && <p style={{ color: '#34d399', fontSize: 11, marginTop: 8 }}>{evalSuccess}</p>}
        {evalError && <p className="inline-error" style={{ marginTop: 8 }}>{evalError}</p>}
      </div>

      <div className="detail-section"><div className="section-label"><MessageSquare size={15} />Evidence<span>{cluster.evidence.length}</span></div><p className="section-intro">What triggered this signal in {rangeLabels[range].toLowerCase()}.</p>
        {cluster.evidence.length ? cluster.evidence.map((evidence, index) => <div className="evidence-card" key={`${evidence.event_id}-${index}`}><span className="evidence-marker">{String(index + 1).padStart(2, '0')}</span><blockquote>“{evidence.content}”</blockquote><p><TriangleAlert size={13} />{evidence.reason}</p><button className="text-button" onClick={() => onConversation(evidence.conversation_id)}>Open conversation<ArrowUpRight size={14} /></button></div>) : <p className="muted">No evidence within this date range. Try a longer range.</p>}
      </div>
      <div className="suggestion-card"><div className="section-label"><Sparkles size={16} />Suggested next step</div><p>{cluster.suggested_fix || 'Review the flagged conversation and reproduce the issue before making a change.'}</p><span>Detector {cluster.detector_version} · rule {cluster.rule_version} · Review and validate before applying.</span></div>
      <div className="detail-section"><div className="section-label"><Layers3 size={15} />Related conversations</div>{cluster.conversations.map(conversation => <button key={conversation.id} className="related-conversation" onClick={() => onConversation(conversation.id)}><MessageSquare size={15} /><span><strong>{shortId(conversation.id)}</strong><small>{conversation.preview}</small></span><ChevronRight size={15} /></button>)}</div>
      <div className="drawer-bottom"><span>Last seen {dateTime(cluster.last_seen)}</span>{saveError && <p className="inline-error">{saveError}</p>}<button className={`button ${cluster.status === 'open' ? 'button-primary' : 'button-secondary'}`} disabled={saving} onClick={async () => {
        setSaving(true); setSaveError('');
        try { await request(`/api/clusters/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ status: cluster.status === 'open' ? 'resolved' : 'open' }) }); resource.retry(); onChanged(); }
        catch (cause) { setSaveError((cause as Error).message); } finally { setSaving(false); }
      }}>{saving ? <LoaderCircle size={16} className="spin" /> : cluster.status === 'open' ? <CheckCheck size={17} /> : <ArrowDownLeft size={17} />}{cluster.status === 'open' ? 'Mark as resolved' : 'Reopen cluster'}</button></div>
    </div>}
  </Modal>;
}

function ConversationDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const resource = useResource<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`);
  const [tab, setTab] = useState<'story' | 'messages' | 'waterfall'>('story');
  const [spanId, setSpanId] = useState<string | null>(null);
  const conversation = resource.data;
  const selectedSpan = conversation?.spans.find(span => span.id === spanId);
  const maxSpanDuration = Math.max(1, ...(conversation?.spans.map(s => s.duration_ms || 0) || [100]));

  return <Modal title="Agent Execution Inspector" onClose={onClose} sheet>
    {resource.loading ? <Loading label="Loading trajectory" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> : conversation && <div className="drawer-content conversation-drawer">
      <div className="drawer-eyebrow"><Status status={conversation.status} /><span>{dateTime(conversation.started_at)}</span></div><div className="conversation-id"><h2>{shortId(conversation.id)}</h2><CopyButton text={conversation.id} compact label="Copy conversation ID" /></div>
      <div className="conversation-metadata"><span><Users size={14} />{conversation.user_id || 'Anonymous user'}</span><span><Bot size={14} />{conversation.model || 'Model not reported'}</span><span><Clock3 size={14} />{latency(conversation.latency_ms)}</span><span>{money(conversation.cost_usd)}</span></div>
      {conversation.signals.length > 0 && <div className="signal-summary"><TriangleAlert size={17} /><div><strong>{conversation.signals.length} {conversation.signals.length === 1 ? 'signal' : 'signals'} intercepted</strong><span>{Array.from(new Set(conversation.signals.map(signal => friendlyKind(signal.kind)))).join(' · ')}</span></div></div>}
      
      <div className="drawer-tabs">
        <button className={tab === 'story' ? 'active' : ''} onClick={() => setTab('story')}><Activity size={15} />Execution Story</button>
        <button className={tab === 'messages' ? 'active' : ''} onClick={() => setTab('messages')}><MessageSquare size={15} />Transcript<span>{conversation.messages.length}</span></button>
        <button className={tab === 'waterfall' ? 'active' : ''} onClick={() => setTab('waterfall')}><GitBranch size={15} />Waterfall<span>{conversation.spans.length}</span></button>
      </div>

      {tab === 'story' && <div className="exec-flow-graph">
        {/* User Prompt Node */}
        <div className="exec-flow-node node-prompt">
          <div className="exec-flow-head">
            <span className="exec-flow-tag"><Users size={12} />User Prompt Ingestion</span>
            <span>{dateTime(conversation.started_at)}</span>
          </div>
          <div className="exec-flow-content">{conversation.preview || conversation.messages.find(m => m.role === 'user')?.content || 'No prompt content'}</div>
          <div className="exec-flow-meta">
            <span>Intent: Analyzed</span>
            <span>User: {conversation.user_id || 'Anonymous'}</span>
          </div>
        </div>
        <div className="exec-flow-connector" />

        {/* Tool Execution Nodes */}
        {conversation.spans.filter(s => s.kind === 'tool' || s.name.includes('.')).map((span) => {
          const isError = span.status === 'error';
          return <div key={span.id} className={`exec-flow-node ${isError ? 'node-error' : 'node-tool'}`}>
            <div className="exec-flow-head">
              <span className="exec-flow-tag" style={{ color: isError ? '#f43f5e' : '#eab308' }}>
                <Terminal size={12} />
                Tool Execution: {span.name}
              </span>
              <span style={{ color: isError ? '#f43f5e' : '#34d399' }}>{isError ? 'STATUS ERROR' : 'STATUS 200 OK'}</span>
            </div>
            <div className="exec-flow-content">
              {typeof span.output === 'string' ? span.output : JSON.stringify(span.output) || 'Tool executed'}
            </div>
            <div className="exec-flow-meta">
              <span>Latency: {latency(span.duration_ms)}</span>
              <span>Span ID: {shortId(span.id)}</span>
            </div>
          </div>;
        })}
        {conversation.spans.filter(s => s.kind === 'tool' || s.name.includes('.')).length > 0 && <div className="exec-flow-connector" />}

        {/* Signals Intercepted Node */}
        {conversation.signals.map(signal => <div key={signal.id} className="exec-flow-node node-error">
          <div className="exec-flow-head">
            <span className="exec-flow-tag" style={{ color: '#f43f5e' }}>
              <TriangleAlert size={12} />
              Guardrail Intercepted: {friendlyKind(signal.kind)}
            </span>
            <span className={`severity severity-${signal.severity}`}><span />{signal.severity}</span>
          </div>
          <div className="exec-flow-content">{signal.reason}</div>
          <div className="exec-flow-meta">
            <span>Rule: v{signal.rule_version}</span>
            <span>Detector: v{signal.detector_version}</span>
          </div>
        </div>)}
        {conversation.signals.length > 0 && <div className="exec-flow-connector" />}

        {/* Agent Turn Outcome */}
        <div className="exec-flow-node node-agent">
          <div className="exec-flow-head">
            <span className="exec-flow-tag" style={{ color: '#818cf8' }}><Bot size={12} />Agent Response Outcome</span>
            <span>{dateTime(conversation.last_at)}</span>
          </div>
          <div className="exec-flow-content">
            {conversation.messages.filter(m => m.role === 'assistant').slice(-1)[0]?.content || 'Agent completed execution'}
          </div>
          <div className="exec-flow-meta">
            <span>Total Latency: {latency(conversation.latency_ms)}</span>
            <span>Cost: {money(conversation.cost_usd)}</span>
            <span>Model: {conversation.model || 'Default'}</span>
          </div>
        </div>
      </div>}

      {tab === 'messages' && <div className="message-timeline">{conversation.messages.map(message => {
        const signals = conversation.signals.filter(signal => signal.event_id === message.id);
        return <div key={message.id} className={`message-entry role-${message.role} ${signals.length ? 'message-flagged' : ''}`}><span className="message-avatar">{message.role === 'assistant' ? <Bot size={16} /> : message.role === 'user' ? <Users size={15} /> : <Terminal size={15} />}</span><div className="message-body"><div className="message-heading"><strong>{message.role === 'assistant' ? 'Agent' : friendlyKind(message.role)}{message.name && <small>{message.name}</small>}</strong><span>{new Date(message.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span></div><p>{message.content}</p>{signals.map(signal => <div key={signal.id} className="message-signal" title={`Detector ${signal.detector_version} · rule ${signal.rule_version}`}><TriangleAlert size={13} /><span>{signal.reason}</span></div>)}{message.status === 'error' && !signals.length && <div className="message-signal"><TriangleAlert size={13} />Reported error</div>}</div></div>;
      })}</div>}

      {tab === 'waterfall' && <div className="waterfall-container">
        <p className="section-intro">Inspect the execution timing of every span in this agent run.</p>
        {conversation.spans.length ? <><div className="waterfall-table">
          <div className="waterfall-head">
            <span>Span / Kind</span>
            <span>Duration Timeline</span>
            <span style={{ textAlign: 'right' }}>Latency</span>
          </div>
          {conversation.spans.map(span => {
            const isError = span.status === 'error';
            const widthPct = Math.max(8, Math.min(100, (span.duration_ms / maxSpanDuration) * 100));
            return <div key={span.id} className={`waterfall-row ${spanId === span.id ? 'selected' : ''}`} onClick={() => setSpanId(span.id)}>
              <span className="waterfall-name">
                {span.kind === 'tool' ? <Terminal size={13} style={{ color: isError ? '#f43f5e' : '#eab308' }} /> : <Bot size={13} style={{ color: '#818cf8' }} />}
                <span>{span.name}</span>
              </span>
              <div className="waterfall-track">
                <div
                  className={`waterfall-bar ${isError ? 'bar-error' : span.kind === 'assistant' ? 'bar-assistant' : ''}`}
                  style={{ width: `${widthPct}%`, left: '0%' }}
                />
              </div>
              <span className="waterfall-duration">{latency(span.duration_ms)}</span>
            </div>;
          })}
        </div>
        {selectedSpan && <div className="span-detail" style={{ marginTop: 14 }}>
          <div className="section-label">{selectedSpan.name}<CopyButton text={selectedSpan.id} label="Copy span ID" compact /></div>
          <span className="span-id">{selectedSpan.id}</span>
          <h4>Input Payload</h4>
          <pre>{typeof selectedSpan.input === 'string' ? selectedSpan.input : JSON.stringify(selectedSpan.input, null, 2) || 'Not reported'}</pre>
          <h4>Output Payload</h4>
          <pre>{typeof selectedSpan.output === 'string' ? selectedSpan.output : JSON.stringify(selectedSpan.output, null, 2) || 'Not reported'}</pre>
        </div>}</> : <EmptyState icon={GitBranch} title="No spans reported" description="Send trace and span IDs with your events to inspect agent execution here." />}
      </div>}
    </div>}
  </Modal>;
}

function SetupStatusCard({ project, refresh }: { project: Project; refresh: number }) {
  const resource = useResource<SetupStatus>(`/api/projects/${encodeURIComponent(project.id)}/setup`, refresh);
  return <section className="setup-step panel"><div className="step-heading"><span className="step-number">04</span><div><h3>Verify traffic arrives</h3><p>Connection status, received events, and ingestion diagnostics for this project.</p></div></div>
    {resource.loading ? <Loading label="Checking connection" /> : resource.error ? <ErrorState message={resource.error} onRetry={resource.retry} /> : resource.data && <div className="connection-details setup-grid">
      <span>Ingest key<strong>{resource.data.key_configured ? 'Configured' : 'Missing'}</strong></span>
      <span>Events received<strong>{formatNumber(resource.data.events_received)}</strong></span>
      <span>Conversations<strong>{formatNumber(resource.data.conversations)}</strong></span>
      <span>Last event<strong>{resource.data.last_event_at ? dateTime(resource.data.last_event_at) : '—'}</strong></span>
      <span>Pending jobs<strong>{formatNumber(resource.data.jobs.pending + resource.data.jobs.failed)}</strong></span>
      <span>Dead jobs<strong>{formatNumber(resource.data.jobs.dead)}</strong></span>
    </div>}
    {resource.data && (resource.data.jobs.failed > 0 || resource.data.jobs.dead > 0) && <p className="inline-error">Some events need attention. Inspect pending/failed work via GET /api/jobs?project_id={shortId(project.id)}.</p>}
  </section>;
}

function IntegrationPage({ project, refresh }: { project: Project; refresh: number }) {
  const [showKey, setShowKey] = useState(false);
  const [key, setKey] = useState('');
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyError, setKeyError] = useState('');
  const [language, setLanguage] = useState('typescript');
  const [endpoint, setEndpoint] = useState(import.meta.env.VITE_INGEST_ENDPOINT || window.location.origin);
  const endpointBase = endpoint.trim().replace(/\/$/, '');
  useEffect(() => { setKey(''); setShowKey(false); setKeyError(''); }, [project.id, refresh]);
  const shownKey = key && showKey ? key : 'tvk_••••••••••••••••••••••••';
  const code = language === 'typescript' ? `import { Tervik } from '@tervik/sdk';\n\nconst tervik = new Tervik({\n  apiKey: process.env.TERVIK_API_KEY!,\n  endpoint: ${JSON.stringify(endpointBase)},\n});\n\ntervik.capture({\n  conversation_id: 'conversation-123',\n  user_id: 'user-456',\n  role: 'user',\n  content: 'Can you help me with my order?',\n});\n\nawait tervik.flush();` : `curl -X POST "${endpointBase}/v1/events" \\\n  -H "Authorization: Bearer $TERVIK_API_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"events": [{\n    "conversation_id": "conversation-123",\n    "user_id": "user-456",\n    "role": "user",\n    "content": "Can you help me with my order?"\n  }]}'`;
  return <div className="integration-layout"><div className="integration-main"><div className="integration-intro"><span className="eyebrow"><Zap size={14} />A SMALL SKILL. A CLEARER PICTURE.</span><h2>Connect in minutes.<br /><span>Learn from every conversation.</span></h2><p>Let your coding agent add Tervik to your project, then follow the conversations that reveal what needs attention.</p></div>
    <section className="setup-step panel"><div className="step-heading"><span className="step-number">01</span><div><h3>Download the skill</h3><p>Add Tervik’s integration instructions to your coding agent.</p></div></div><div className="command-box"><code>{INSTALL_COMMAND}</code><CopyButton text={INSTALL_COMMAND} /></div><div className="step-footer"><span>Works with agents that support skills</span><a href="/tervik-skill.zip" download className="text-button"><Download size={14} />Download ZIP</a></div></section>
    <section className="setup-step panel"><div className="step-heading"><span className="step-number">02</span><div><h3>Run this prompt</h3><p>Your agent will read the skill and implement the integration.</p></div></div><div className="command-box prompt-box"><code>{INSTALL_PROMPT}</code><CopyButton text={INSTALL_PROMPT} /></div><div className="step-footer"><span>Review your agent’s code changes before running them.</span></div></section>
    <section className="setup-step panel"><div className="step-heading"><span className="step-number">03</span><div><h3>Set your project key</h3><p>Store this key in your application’s server environment.</p></div></div><label className="field-label">TERVIK_API_KEY</label><div className="key-box"><code>{shownKey}</code><button className="icon-button" title={showKey ? 'Hide API key' : 'Reveal API key'} aria-label={showKey ? 'Hide API key' : 'Reveal API key'} disabled={keyBusy} onClick={async () => {
      if (showKey) { setShowKey(false); return; }
      if (key) { setShowKey(true); return; }
      setKeyBusy(true); setKeyError('');
      try { const result = await request<{ api_key: string }>(`/api/projects/${encodeURIComponent(project.id)}/key`); setKey(result.api_key); setShowKey(true); }
      catch (cause) { setKeyError((cause as Error).message); } finally { setKeyBusy(false); }
    }}>{keyBusy ? <LoaderCircle size={16} className="spin" /> : showKey ? <EyeOff size={17} /> : <Eye size={17} />}</button>{key && showKey && <CopyButton text={key} compact label="Copy API key" />}</div>{keyError && <p className="inline-error">{keyError}</p>}<div className="key-note"><ShieldCheck size={14} />Keep your project key on the server, outside prompts and browser code.</div><label className="field-label endpoint-label" htmlFor="ingestion-endpoint">Ingestion endpoint</label><input id="ingestion-endpoint" className="text-field" type="url" value={endpoint} onChange={event => setEndpoint(event.target.value)} /><p className="endpoint-note">Use a URL reachable from your agent’s server. The local dashboard proxies ingestion to the API.</p></section>
    <section className="code-section panel"><div className="panel-heading"><div><h3>Prefer a direct integration?</h3><p>Send conversation events from your server.</p></div><Code2 size={20} /></div><div className="code-tabs"><div>{[['typescript', 'TypeScript'], ['curl', 'HTTP / cURL']].map(([value, label]) => <button key={value} onClick={() => setLanguage(value)} className={language === value ? 'active' : ''}>{label}</button>)}</div><CopyButton text={code} label="Copy code" /></div><pre className="code-block"><code>{code}</code></pre><div className="code-note">{language === 'typescript' ? 'The SDK is included in this repository as @tervik/sdk. Build it locally; package registry publishing is pending.' : 'Use your project key in the TERVIK_API_KEY environment variable. Ingestion requires a project key.'}</div></section>
    <SetupStatusCard project={project} refresh={refresh} />
  </div><aside className="integration-aside"><div className="setup-project-card"><span className="aside-label">CURRENT PROJECT</span><span className="project-cube"><Layers3 size={23} /></span><h3>{project.name}</h3><p>{project.is_demo ? 'Sample workspace' : 'Your agent workspace'}</p><div><span>Project ID</span><code>{shortId(project.id)}</code><CopyButton text={project.id} compact label="Copy project ID" /></div></div><div className="what-gets-tracked"><h3>A little context goes a long way.</h3>{[[MessageSquare, 'Messages & conversations', 'Group interactions by conversation and user.'], [GitBranch, 'Tools & traces', 'Explore reported tool execution and failures.'], [Clock3, 'Latency & cost', 'Understand the performance you report.']].map(([Icon, title, text]) => {
    const ItemIcon = Icon as LucideIcon;
    return <div key={title as string}><ItemIcon size={19} /><span><strong>{title as string}</strong><p>{text as string}</p></span></div>;
  })}</div><div className="foundation-note"><span className="pulse-dot" /><strong>Local foundation</strong><p>This version runs on your machine. Signals use transparent rules; hosted access, semantic clustering, and automated fixes are future milestones.</p></div></aside></div>;
}

function AgentExecutionSimulator({ onStart }: { onStart: () => void }) {
  const [stage, setStage] = useState<1 | 2 | 3 | 4 | 5>(1);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    if (!isPlaying) return;
    const interval = setInterval(() => {
      setStage(s => (s === 5 ? 1 : ((s + 1) as 1 | 2 | 3 | 4 | 5)));
    }, 3200);
    return () => clearInterval(interval);
  }, [isPlaying]);

  return <div className="m-sim-wrapper">
    <div className="m-sim-card">
      <div className="m-sim-header">
        <div className="m-sim-header-left">
          <div className="m-window-dots">
            <span className="m-dot m-dot-red" />
            <span className="m-dot m-dot-yellow" />
            <span className="m-dot m-dot-green" />
          </div>
          <div className="m-sim-telemetry-strip">
            <span className="m-sim-telemetry-item">RUN: <strong>#exec-8192</strong></span>
            <span className="m-sim-telemetry-item">LATENCY: <strong>{stage === 1 ? '12ms' : stage === 2 ? '4.1s' : stage === 3 ? '4.1s' : stage === 4 ? '4.1s' : '182ms'}</strong></span>
            <span className="m-sim-telemetry-item">TOKENS: <strong>{stage === 1 ? '48' : stage >= 2 ? '342 ($0.0012)' : '0'}</strong></span>
          </div>
        </div>
        <div className={`m-sim-phase-pill phase-${stage}`}>
          <span className="pulse-dot" style={{ display: 'inline-block' }} />
          <span>{stage === 1 ? '01 Prompt Ingestion' : stage === 2 ? '02 Spans Executing' : stage === 3 ? '03 Rule Intercept' : stage === 4 ? '04 Cluster Synthesis' : '05 Replay Verified'}</span>
        </div>
      </div>

      <div className="m-sim-nav">
        {[
          { id: 1, label: '01 Ingest Prompt' },
          { id: 2, label: '02 Tool Spans' },
          { id: 3, label: '03 Rule Intercept' },
          { id: 4, label: '04 Cluster Synthesis' },
          { id: 5, label: '05 Replay Verified' },
        ].map(item => <button
          key={item.id}
          className={`m-sim-nav-btn ${stage === item.id ? 'active' : ''}`}
          onClick={() => { setStage(item.id as any); setIsPlaying(false); }}
        >
          <span className="m-sim-nav-num">0{item.id}</span>
          <span>{item.label}</span>
        </button>)}
      </div>

      <div className="m-sim-body">
        {/* Left Column: The Agent Story */}
        <div className="m-sim-col">
          <div className="m-sim-panel-box">
            <div className="m-sim-panel-title">
              <span>USER PROMPT & RUNTIME CONTEXT</span>
              <span className="status status-healthy"><span />Buffered</span>
            </div>
            <div className="m-chat-message m-chat-user" style={{ marginBottom: 12 }}>
              <span className="m-chat-avatar"><Users size={13} /></span>
              <div>
                <strong>User Input</strong>
                <p>Deploy the updated Stripe webhook migration to production.</p>
              </div>
            </div>
            <div className="m-sim-span-meta" style={{ fontSize: 10 }}>
              <span>Environment: <strong>Production-US-East</strong></span>
              <span>Model: <strong>sample-agent-v1</strong></span>
              <span>Context: <strong>4.2k tokens</strong></span>
            </div>
          </div>

          <div className="m-sim-panel-box">
            <div className="m-sim-panel-title">
              <span>TOOL EXECUTION SPANS</span>
              <span>{stage >= 2 ? '3 spans dispatched' : 'Pending dispatch'}</span>
            </div>
            <div className="m-sim-span-list">
              <div className={`m-sim-span-row ${stage >= 2 ? 'success' : ''}`}>
                <div className="m-sim-span-left">
                  {stage >= 2 ? <Check size={12} color="#34d399" /> : <Clock3 size={12} />}
                  <span>tool: verify_database_connection</span>
                </div>
                <div className="m-sim-span-meta">
                  <span>14ms</span>
                  <span>200 OK</span>
                </div>
              </div>
              <div className={`m-sim-span-row ${stage >= 2 ? 'success' : ''}`}>
                <div className="m-sim-span-left">
                  {stage >= 2 ? <Check size={12} color="#34d399" /> : <Clock3 size={12} />}
                  <span>tool: check_migration_checksums</span>
                </div>
                <div className="m-sim-span-meta">
                  <span>38ms</span>
                  <span>200 OK</span>
                </div>
              </div>
              <div className={`m-sim-span-row ${stage >= 2 ? (stage >= 5 ? 'success' : 'error') : ''}`}>
                <div className="m-sim-span-left">
                  {stage >= 5 ? <Check size={12} color="#34d399" /> : stage >= 2 ? <TriangleAlert size={12} color="#f43f5e" /> : <Clock3 size={12} />}
                  <span>tool: execute_migration</span>
                </div>
                <div className="m-sim-span-meta">
                  <span>{stage >= 5 ? '130ms (fallback retry)' : '4,120ms'}</span>
                  <span style={{ color: stage >= 5 ? '#34d399' : stage >= 2 ? '#f43f5e' : 'inherit' }}>
                    {stage >= 5 ? '200 OK' : stage >= 2 ? '504 TIMEOUT' : 'QUEUED'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Tervik Intelligence & Verification */}
        <div className="m-sim-col">
          {stage === 1 && <div className="m-sim-panel-box">
            <div className="m-sim-panel-title">
              <span>LAYER 1 · TELEMETRY INGESTION</span>
              <span style={{ color: '#38bdf8' }}>Async Ingest</span>
            </div>
            <p style={{ fontSize: 12, color: '#a1a1aa', lineHeight: 1.6, marginBottom: 14 }}>
              As soon as a user sends a prompt, Tervik records the turn with non-blocking async background flush. Sub-2ms overhead on your agent process.
            </p>
            <div className="m-term-line" style={{ background: '#0c0d12', padding: '10px 12px', borderRadius: 6, fontSize: 11 }}>
              <span style={{ color: '#38bdf8' }}>✓ Ingested turn:</span> 1 prompt, 0 errors, ready for tool execution telemetry.
            </div>
          </div>}

          {stage === 2 && <div className="m-sim-panel-box">
            <div className="m-sim-panel-title">
              <span>LAYER 2 · EXECUTION RUNTIME</span>
              <span style={{ color: '#818cf8' }}>Active Spans</span>
            </div>
            <p style={{ fontSize: 12, color: '#a1a1aa', lineHeight: 1.6, marginBottom: 14 }}>
              Sub-spans branch out across tools, APIs, and file operations. Latency, payload inputs, and error statuses are recorded in real time.
            </p>
            <div style={{ background: 'rgba(244, 63, 94, 0.08)', border: '1px solid rgba(244, 63, 94, 0.25)', borderRadius: 6, padding: '10px 12px', fontSize: 11, color: '#f43f5e' }}>
              <strong>Exception Caught:</strong> worker pool timeout (504) after 4,120ms.
            </div>
          </div>}

          {stage === 3 && <div className="m-sim-panel-box">
            <div className="m-sim-panel-title">
              <span>LAYER 2 · DETERMINISTIC TRIAGE</span>
              <span className="severity severity-critical"><span />Critical Intercept</span>
            </div>
            <div className="m-signal-card" style={{ marginTop: 0 }}>
              <div className="m-signal-head">
                <TriangleAlert size={14} />
                <strong>Signal #SIG-409 · Tool Timeout</strong>
                <span className="severity severity-critical"><span />Critical</span>
              </div>
              <p>Rule &quot;required_tool&quot; violated: execute_migration timed out after 4000ms deadline.</p>
              <div className="m-signal-meta">
                <span>Rule: v1</span>
                <span>Transparent Regex Guardrail</span>
                <span>0 Hallucinated LLM tokens</span>
              </div>
            </div>
          </div>}

          {stage === 4 && <div className="m-sim-panel-box">
            <div className="m-sim-panel-title">
              <span>LAYER 3 · CROSS-SESSION CLUSTER</span>
              <span className="count-badge">42 runs</span>
            </div>
            <div className="m-cluster-card" style={{ marginTop: 0 }}>
              <div className="m-cluster-head">
                <Layers3 size={14} />
                <strong>Cluster #03 · Database Pool Exhaustion</strong>
                <span className="count-badge">10.7% Traffic Share</span>
              </div>
              <p>Postgres connection pool exhaustion observed across 6 distinct users during peak deployment windows.</p>
              <div className="m-cluster-action">
                <span>Evidence cited with exact payload</span>
                <button className="text-button" onClick={onStart}>Investigate in dashboard<ChevronRight size={13} /></button>
              </div>
            </div>
          </div>}

          {stage === 5 && <div className="m-sim-panel-box" style={{ borderColor: 'rgba(52, 211, 153, 0.3)', background: 'rgba(52, 211, 153, 0.04)' }}>
            <div className="m-sim-panel-title">
              <span style={{ color: '#34d399' }}>LAYER 4 · REPLAY EVALUATION LAB</span>
              <span className="status status-healthy"><span />System Verified</span>
            </div>
            <p style={{ fontSize: 12, color: '#d4d4d8', lineHeight: 1.6, marginBottom: 12 }}>
              A candidate prompt & tool descriptor with exponential backoff and circuit breaker was simulated across 42 historical production failure cases.
            </p>
            <div style={{ background: '#090b10', border: '1px solid rgba(52, 211, 153, 0.2)', borderRadius: 6, padding: '10px 14px', fontSize: 11, fontFamily: 'Geist Mono, monospace', marginBottom: 12 }}>
              <div style={{ color: '#71717a', marginBottom: 4 }}>BASELINE: 0 / 42 passed (42 violations)</div>
              <div style={{ color: '#34d399', fontWeight: 600 }}>CANDIDATE: 42 / 42 passed (0 violations) · 100% PASS</div>
            </div>
            <span style={{ fontSize: 11, color: '#34d399', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Check size={14} />
              Zero regressions detected. Ready for production rollout.
            </span>
          </div>}
        </div>
      </div>

      <div className="m-sim-controls">
        <span>Click tabs or advance to see how Tervik turns execution friction into verified fixes.</span>
        <div className="m-sim-controls-actions">
          <button className="m-sim-btn-step" onClick={() => setIsPlaying(!isPlaying)}>
            {isPlaying ? <Pause size={13} /> : <Play size={13} />}
            <span>{isPlaying ? 'Pause' : 'Autoplay'}</span>
          </button>
          <button
            className="m-sim-btn-step"
            onClick={() => { setStage(s => (s === 1 ? 5 : ((s - 1) as any))); setIsPlaying(false); }}
          >
            <span>Prev</span>
          </button>
          <button
            className="m-sim-btn-step m-sim-btn-primary"
            onClick={() => { setStage(s => (s === 5 ? 1 : ((s + 1) as any))); setIsPlaying(false); }}
          >
            <span>{stage === 5 ? 'Restart Cycle' : 'Next Phase'}</span>
            {stage === 5 ? <RotateCcw size={13} /> : <ChevronRight size={13} />}
          </button>
        </div>
      </div>
    </div>
  </div>;
}

function Welcome({ onStart, onDemo, demoBusy }: { onStart: () => void; onDemo: () => void; demoBusy: boolean }) {
  const [activeStep, setActiveStep] = useState<'install' | 'prompt' | 'observe'>('install');
  const [expandedFaq, setExpandedFaq] = useState<number | null>(0);
  const [copiedCmd, setCopiedCmd] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const copyHeroCmd = async () => {
    try {
      await navigator.clipboard.writeText(INSTALL_COMMAND);
      setCopiedCmd(true);
      setTimeout(() => setCopiedCmd(false), 2000);
    } catch {
      // ignore
    }
  };

  const faqs = [
    {
      q: 'Does Tervik work with my existing agent framework?',
      a: 'Yes. Tervik works with Claude Code, Cursor, OpenCode, Codex, Devin, Antigravity, LangChain, LlamaIndex, or any custom agent harness. You can install the Tervik skill or use the @tervik/sdk client library.',
    },
    {
      q: 'How does deterministic failure detection differ from LLM-as-a-judge?',
      a: 'LLM judges are slow, costly, and non-deterministic. Tervik evaluates conversation turns using transparent, rule-based triage: required tools, forbidden patterns, repetition loops, and tool execution error payloads—with zero hallucinations.',
    },
    {
      q: 'Where is my conversation data stored?',
      a: 'Tervik runs on your local machine or private cloud. All conversations, failure clusters, and evidence are stored in your own SQLite or PostgreSQL database. Your data is never sent to our servers.',
    },
    {
      q: 'What is the latency overhead on agent inference calls?',
      a: 'Virtually zero (~2ms). Events are buffered and flushed asynchronously in the background, so your agent generation loops and user interactions are never blocked.',
    },
    {
      q: 'Can we define custom rules and alert channels?',
      a: 'Yes. You can define custom behavior rules (forbidden phrases, mandatory tools) and set up threshold or trend-based alerts that notify your team via Slack webhooks or email.',
    },
  ];

  return <div className="m-page">
    {/* Floating Frosted Navigation Bar */}
    <header className="m-nav-wrapper">
      <nav className="m-navbar">
        <a href="#welcome" className="m-brand">
          <span className="logo-symbol"><span /></span>
          <span className="m-brand-text">tervik<span className="logo-dot">.</span></span>
        </a>

        <div className="m-nav-links">
          <a href="#how-it-works">How It Works</a>
          <a href="#setup-steps">Setup</a>
          <a href="#features">Features</a>
          <a href="#case-studies">Case Studies</a>
          <a href="#faq">FAQ</a>
        </div>

        <div className="m-nav-actions">
          <button className="button button-secondary m-nav-demo-btn" disabled={demoBusy} onClick={onDemo}>
            {demoBusy ? <LoaderCircle size={14} className="spin" /> : <Layers3 size={14} />}
            <span>Sample Data</span>
          </button>
          <button className="button button-primary m-nav-start-btn" onClick={onStart}>
            <span>Dashboard</span>
            <ChevronRight size={14} />
          </button>
          <button className="icon-button m-nav-mobile-toggle" onClick={() => setMobileMenuOpen(!mobileMenuOpen)} aria-label="Toggle navigation">
            {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </nav>

      {mobileMenuOpen && <div className="m-mobile-menu">
        <a href="#how-it-works" onClick={() => setMobileMenuOpen(false)}>01 · How It Works</a>
        <a href="#setup-steps" onClick={() => setMobileMenuOpen(false)}>02 · Setup in 3 Steps</a>
        <a href="#features" onClick={() => setMobileMenuOpen(false)}>03 · Features</a>
        <a href="#case-studies" onClick={() => setMobileMenuOpen(false)}>04 · Case Studies</a>
        <a href="#faq" onClick={() => setMobileMenuOpen(false)}>05 · FAQ</a>
        <div className="m-mobile-menu-actions">
          <button className="button button-secondary" disabled={demoBusy} onClick={() => { setMobileMenuOpen(false); onDemo(); }}>
            {demoBusy ? <LoaderCircle size={14} className="spin" /> : <Layers3 size={14} />}
            <span>Explore Sample Workspace</span>
          </button>
          <button className="button button-primary" onClick={() => { setMobileMenuOpen(false); onStart(); }}>
            <span>Open Dashboard</span>
            <ChevronRight size={14} />
          </button>
        </div>
      </div>}
    </header>

    {/* Hero Section */}
    <section className="m-hero">
      <div className="m-hero-badge">
        <span className="pulse-dot" />
        <span>AGENT CONVERSATION INTELLIGENCE</span>
        <span className="m-badge-divider">·</span>
        <span className="m-badge-dim">LOCAL-FIRST</span>
      </div>

      <h1 className="m-hero-title">
        Procedural Intelligence &amp;<br />
        Failure Detection For Agents.
      </h1>

      <p className="m-hero-subtitle">
        Tervik records every turn, evaluates failure signals with transparent rules, and synthesizes clusters with evidence. Fewer turns, zero blind spots, and continuous improvement.
      </p>

      <div className="m-hero-actions">
        <button className="button button-primary m-hero-btn" onClick={onStart}>
          <span>Dashboard</span>
          <ArrowRight size={16} />
        </button>

        <div className="m-hero-cmd-box" onClick={copyHeroCmd} title="Click to copy">
          <Terminal size={14} className="m-hero-cmd-icon" />
          <code>{INSTALL_COMMAND}</code>
          <button className="icon-button m-hero-copy-btn" aria-label="Copy install command">
            {copiedCmd ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
      </div>

      <div className="m-hero-partners">
        <span className="m-partners-label">WORKS WITH</span>
        <div className="m-partners-list">
          <span>Claude Code</span>
          <span>Cursor</span>
          <span>OpenCode</span>
          <span>Codex</span>
          <span>Devin</span>
          <span>Antigravity</span>
          <span>LangChain</span>
        </div>
      </div>

      {/* Interactive Agent Execution Simulator */}
      <AgentExecutionSimulator onStart={onStart} />
    </section>

    {/* Section Divider */}
    <div className="m-divider" />

    {/* How It Works (4 Layers) */}
    <section id="how-it-works" className="m-section">
      <div className="m-section-header">
        <span className="m-section-eyebrow">FOUR DETERMINISTIC LAYERS</span>
        <h2 className="m-section-title">How It Works.</h2>
        <p className="m-section-subtitle">
          From raw trace ingestion to reproducible evaluation, Tervik gives your agents a systematic feedback loop.
        </p>
      </div>

      <div className="m-layers-grid">
        <div className="m-layer-card m-layer-1">
          <div className="m-layer-header">
            <span className="m-layer-pill">LAYER 1</span>
            <span className="m-layer-name">Traces &amp; Telemetry</span>
          </div>
          <h3>The raw record of an agent run</h3>
          <p>
            Prompts, assistant turns, tool executions, latency, and cost captured seamlessly via skill or SDK without altering agent architectures.
          </p>
          <div className="m-layer-spec">
            <span>Non-blocking async flush</span>
            <span>Zero telemetry drops</span>
          </div>
        </div>

        <div className="m-layer-card m-layer-2">
          <div className="m-layer-header">
            <span className="m-layer-pill">LAYER 2</span>
            <span className="m-layer-name">Signal &amp; Failure Detection</span>
          </div>
          <h3>Deterministic triage on every turn</h3>
          <p>
            Deterministic triage rules catch tool exceptions, customer corrections, repetition loops, and forbidden phrase violations in real time.
          </p>
          <div className="m-layer-spec">
            <span>No flaky judge models</span>
            <span>Transparent regex rules</span>
          </div>
        </div>

        <div className="m-layer-card m-layer-3">
          <div className="m-layer-header">
            <span className="m-layer-pill">LAYER 3</span>
            <span className="m-layer-name">Cluster Synthesis</span>
          </div>
          <h3>Connect patterns across sessions</h3>
          <p>
            Recurring failure signals group automatically into clusters. Every cluster cites exact excerpts, affected user counts, and share percentages.
          </p>
          <div className="m-layer-spec">
            <span>Evidence cited for every issue</span>
            <span>Prioritized by severity</span>
          </div>
        </div>

        <div className="m-layer-card m-layer-4">
          <div className="m-layer-header">
            <span className="m-layer-pill">LAYER 4</span>
            <span className="m-layer-name">Evaluation &amp; Replay</span>
          </div>
          <h3>Verify fixes before deployment</h3>
          <p>
            Turn production findings into replay evaluation datasets. Compare baseline vs candidate agent descriptors across edge cases before pushing code.
          </p>
          <div className="m-layer-spec">
            <span>Regression prevention</span>
            <span>Reproducibility scoring</span>
          </div>
        </div>
      </div>
    </section>

    {/* Section Divider */}
    <div className="m-divider" />

    {/* Set Up In Three Steps */}
    <section id="setup-steps" className="m-section">
      <div className="m-section-header">
        <span className="m-section-eyebrow">FAST ONBOARDING</span>
        <h2 className="m-section-title">Set Up In Three Steps.</h2>
        <p className="m-section-subtitle">
          Connect your agent in two minutes. Start seeing signals on your very next turn.
        </p>

        <div className="m-steps-tabs">
          <button className={`m-step-tab ${activeStep === 'install' ? 'active' : ''}`} onClick={() => setActiveStep('install')}>
            <span className="m-step-tab-num">01</span>
            <span>Install</span>
          </button>
          <button className={`m-step-tab ${activeStep === 'prompt' ? 'active' : ''}`} onClick={() => setActiveStep('prompt')}>
            <span className="m-step-tab-num">02</span>
            <span>Run Prompt</span>
          </button>
          <button className={`m-step-tab ${activeStep === 'observe' ? 'active' : ''}`} onClick={() => setActiveStep('observe')}>
            <span className="m-step-tab-num">03</span>
            <span>Observe</span>
          </button>
        </div>
      </div>

      <div className="m-steps-display">
        <div className="m-steps-terminal">
          <div className="m-terminal-top">
            <div className="m-window-dots">
              <span className="m-dot m-dot-red" />
              <span className="m-dot m-dot-yellow" />
              <span className="m-dot m-dot-green" />
            </div>
            <span className="m-terminal-title">bash — 80x24</span>
            <CopyButton
              text={activeStep === 'install' ? INSTALL_COMMAND : activeStep === 'prompt' ? INSTALL_PROMPT : 'npm run dev'}
              compact
            />
          </div>

          <div className="m-terminal-content">
            {activeStep === 'install' && <>
              <div className="m-term-line"><span className="m-term-prompt">$</span> {INSTALL_COMMAND}</div>
              <div className="m-term-out text-zinc-400">Fetching skill definition from dhanvin-ai/tervik...</div>
              <div className="m-term-out text-emerald-400">✔ Added skill &quot;tervik&quot; to current workspace</div>
              <div className="m-term-out text-zinc-500">Skill location: .agents/skills/tervik/SKILL.md</div>
              <div className="m-term-out text-zinc-400">Telemetry endpoints registered. Ready for agent execution.</div>
            </>}

            {activeStep === 'prompt' && <>
              <div className="m-term-line"><span className="m-term-prompt">&gt;</span> {INSTALL_PROMPT}</div>
              <div className="m-term-out text-zinc-400">Agent reading skill instructions from .agents/skills/tervik/SKILL.md...</div>
              <div className="m-term-out text-zinc-400">Inspecting application routes and agent runner setup...</div>
              <div className="m-term-out text-emerald-400">✔ Added @tervik/sdk integration hook</div>
              <div className="m-term-out text-emerald-400">✔ Wired conversation error and tool telemetry captures</div>
              <div className="m-term-out text-zinc-500">Integration completed with 0 compile errors.</div>
            </>}

            {activeStep === 'observe' && <>
              <div className="m-term-line"><span className="m-term-prompt">$</span> node scripts/dev.mjs</div>
              <div className="m-term-out text-zinc-400">Starting Tervik ingestion API on http://127.0.0.1:8000...</div>
              <div className="m-term-out text-zinc-400">Launching web dashboard on http://127.0.0.1:5173...</div>
              <div className="m-term-out text-emerald-400">✔ Connected to project: Sample workspace</div>
              <div className="m-term-out text-white font-medium">56 conversations indexed · 3 failure clusters detected</div>
              <div className="m-term-out text-zinc-500">Ready to triage and evaluate incoming events.</div>
            </>}
          </div>
        </div>

        <div className="m-steps-info">
          {activeStep === 'install' && <>
            <span className="m-info-step-label">STEP 01</span>
            <h3>Add the skill in one command</h3>
            <p>
              Installs Tervik’s standardized integration instructions into your agent workspace. Compatible with Claude Code, Cursor, OpenCode, Codex, and Devin.
            </p>
            <div className="m-info-check">
              <Check size={16} />
              <span>Zero external credentials required for local mode</span>
            </div>
          </>}

          {activeStep === 'prompt' && <>
            <span className="m-info-step-label">STEP 02</span>
            <h3>Prompt your agent to implement it</h3>
            <p>
              Your agent reads the instructions and wires conversation capture directly into your application’s existing tool and chat handlers.
            </p>
            <div className="m-info-check">
              <Check size={16} />
              <span>Full control over every code diff your agent makes</span>
            </div>
          </>}

          {activeStep === 'observe' && <>
            <span className="m-info-step-label">STEP 03</span>
            <h3>Inspect evidence and failure clusters</h3>
            <p>
              Every conversation flows into Tervik. Friction is grouped, tool failures cite exact payloads, and candidates can be replayed safely.
            </p>
            <div className="m-info-check">
              <Check size={16} />
              <span>Interactive trace explorer and cluster management</span>
            </div>
          </>}
        </div>
      </div>
    </section>

    {/* Section Divider */}
    <div className="m-divider" />

    {/* Built For Production AI Agents (Features Bento Grid) */}
    <section id="features" className="m-section">
      <div className="m-section-header">
        <span className="m-section-eyebrow">ENTERPRISE PRECISION</span>
        <h2 className="m-section-title">Built For Production AI Agents.</h2>
        <p className="m-section-subtitle">
          Everything you need to observe, triage, and validate agent behavior in high-stakes environments.
        </p>
      </div>

      <div className="m-bento-grid">
        <div className="m-bento-card">
          <div className="m-bento-icon"><Zap size={20} /></div>
          <h3>Sub-2ms Ingestion</h3>
          <p>Non-blocking asynchronous event batching. Zero latency added to agent generation loops or tool executions.</p>
        </div>

        <div className="m-bento-card">
          <div className="m-bento-icon"><ShieldCheck size={20} /></div>
          <h3>Deterministic Guardrails</h3>
          <p>No fuzzy judge models that hallucinate. Transparent regex patterns, required tools, and failure thresholds.</p>
        </div>

        <div className="m-bento-card">
          <div className="m-bento-icon"><MessageSquare size={20} /></div>
          <h3>Evidence-Backed Clusters</h3>
          <p>Every cluster cites exact conversation excerpts, user IDs, and timestamps. Never guess why an agent stumbled.</p>
        </div>

        <div className="m-bento-card">
          <div className="m-bento-icon"><Layers3 size={20} /></div>
          <h3>Local &amp; Self-Hosted</h3>
          <p>Runs locally or self-hosted with SQLite or PostgreSQL. Your customer conversations never leave your infrastructure.</p>
        </div>

        <div className="m-bento-card">
          <div className="m-bento-icon"><GitBranch size={20} /></div>
          <h3>Candidate Replay Evals</h3>
          <p>Evaluate prompt or tool adjustments across historical production failures before deploying changes to live users.</p>
        </div>

        <div className="m-bento-card">
          <div className="m-bento-icon"><Code2 size={20} /></div>
          <h3>Universal Compatibility</h3>
          <p>Drop-in skill and TypeScript SDK. Works with Claude Code, Cursor, OpenCode, Codex, Devin, and custom frameworks.</p>
        </div>
      </div>
    </section>

    {/* Section Divider */}
    <div className="m-divider" />

    {/* Case Studies & Impact */}
    <section id="case-studies" className="m-section">
      <div className="m-section-header">
        <span className="m-section-eyebrow">VERIFIED OUTCOMES</span>
        <h2 className="m-section-title">Case Studies &amp; Impact Metrics.</h2>
        <p className="m-section-subtitle">
          Measured outcomes from engineering teams building autonomous AI agents with Tervik.
        </p>
      </div>

      <div className="m-stats-row">
        <div className="m-stat-card">
          <strong className="m-stat-number">100%</strong>
          <span className="m-stat-label">Evidence-Backed Triage</span>
          <p>Every cluster cites real messages and tool payloads. Zero ungrounded summaries.</p>
        </div>

        <div className="m-stat-card">
          <strong className="m-stat-number">98%</strong>
          <span className="m-stat-label">Faster Diagnosis</span>
          <p>Zero manual log scouring across distributed agent workers and nested spans.</p>
        </div>

        <div className="m-stat-card">
          <strong className="m-stat-number">40%</strong>
          <span className="m-stat-label">Fewer Repeated Errors</span>
          <p>Catch recurring failure loops and prompt regressions before they affect users.</p>
        </div>
      </div>

      <div className="m-quote-card">
        <blockquote>
          &quot;Tervik gave our coding agent the visibility it was missing. Within 10 minutes we found two repeated tool error loops that were silently frustrating users.&quot;
        </blockquote>
        <div className="m-quote-author">
          <span className="user-avatar">A</span>
          <div>
            <strong>Autonomous Agent Infrastructure Team</strong>
            <small>Production agent deployment · 100k+ monthly runs</small>
          </div>
        </div>
      </div>
    </section>

    {/* Section Divider */}
    <div className="m-divider" />

    {/* FAQ Accordion */}
    <section id="faq" className="m-section">
      <div className="m-section-header">
        <span className="m-section-eyebrow">COMMON QUESTIONS</span>
        <h2 className="m-section-title">Frequently Asked Questions.</h2>
        <p className="m-section-subtitle">
          Everything you need to know about Tervik&apos;s architecture, privacy, and integrations.
        </p>
      </div>

      <div className="m-faq-container">
        {faqs.map((faq, index) => {
          const isOpen = expandedFaq === index;
          return <div key={faq.q} className={`m-faq-item ${isOpen ? 'open' : ''}`}>
            <button className="m-faq-trigger" onClick={() => setExpandedFaq(isOpen ? null : index)}>
              <span>{faq.q}</span>
              {isOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
            </button>
            {isOpen && <div className="m-faq-answer">
              <p>{faq.a}</p>
            </div>}
          </div>;
        })}
      </div>
    </section>

    {/* Grand CTA Banner */}
    <section className="m-cta-section">
      <div className="m-cta-glow" />
      <div className="m-cta-content">
        <span className="m-cta-eyebrow">READY TO LISTEN?</span>
        <h2>Build Agents That Get Better Every Turn.</h2>
        <p>Install the skill, connect your agent, and see where conversations stumble in minutes.</p>

        <div className="m-cta-buttons">
          <button className="button button-primary m-cta-btn" onClick={onStart}>
            <span>Open Dashboard</span>
            <ChevronRight size={16} />
          </button>
          <button className="button button-secondary m-cta-btn" disabled={demoBusy} onClick={onDemo}>
            {demoBusy ? <LoaderCircle size={15} className="spin" /> : <Layers3 size={15} />}
            <span>Explore Sample Workspace</span>
          </button>
        </div>

        <div className="m-cta-snippet" onClick={copyHeroCmd} title="Click to copy">
          <Terminal size={14} />
          <code>{INSTALL_COMMAND}</code>
          {copiedCmd ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
        </div>
      </div>
    </section>

    {/* Footer */}
    <footer className="m-footer">
      <div className="m-footer-top">
        <div className="m-footer-brand">
          <div className="logo">
            <span className="logo-symbol"><span /></span>
            <span>tervik<span className="logo-dot">.</span></span>
          </div>
          <p>Find failures. Understand friction. Build better AI agents.</p>
          <div className="m-footer-local-badge">
            <span className="local-dot" />
            <span>Local Foundation · Transparent Rules</span>
          </div>
        </div>

        <div className="m-footer-cols">
          <div className="m-footer-col">
            <h4>Product</h4>
            <a href="#how-it-works">How It Works</a>
            <a href="#setup-steps">Setup in 3 Steps</a>
            <a href="#features">Features</a>
            <a href="#case-studies">Case Studies</a>
          </div>

          <div className="m-footer-col">
            <h4>Documentation</h4>
            <a href="#integration" onClick={onStart}>SDK &amp; Ingestion</a>
            <a href="#setup-steps">Skill Guide</a>
            <a href="#faq">FAQ</a>
            <a href="/tervik-skill.zip" download>Download ZIP</a>
          </div>

          <div className="m-footer-col">
            <h4>Connect</h4>
            <a href="https://github.com/dhanvin-ai/tervik" target="_blank" rel="noreferrer">
              <span>GitHub</span>
              <ExternalLink size={12} />
            </a>
            <a href="https://twitter.com" target="_blank" rel="noreferrer">
              <span>Twitter / X</span>
              <ExternalLink size={12} />
            </a>
            <button className="text-button" onClick={onStart}>Dashboard</button>
          </div>
        </div>
      </div>

      <div className="m-footer-bottom">
        <span>&copy; {new Date().getFullYear()} Tervik. All rights reserved.</span>
        <span>Procedural Conversation Intelligence</span>
      </div>
    </footer>
  </div>;
}

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const [projectId, setProjectId] = useState(localStorage.getItem('tervik_project') || '');
  const [range, setRange] = useState<Range>('7d');
  const [refresh, setRefresh] = useState(0);
  const [clusterId, setClusterId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState('');
  const [demoBusy, setDemoBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [adminToken, setAdminToken] = useState(sessionStorage.getItem('tervik_admin_token') || '');
  const [sessionToken, setSessionToken] = useState(sessionStorage.getItem('tervik_session') || '');
  const pendingProject = useRef<string | null>(null);
  const projects = useResource<Project[]>('/api/projects', refresh);
  const health = useResource<{ status: string; storage: string; analysis_mode: string }>('/api/health', refresh);
  const project = projects.data?.find(item => item.id === projectId) || (pendingProject.current ? undefined : projects.data?.[0]);
  const overview = useResource<Overview>(project ? `/api/overview${query({ project_id: project.id, range })}` : null, refresh);
  useEffect(() => {
    const change = () => { setPage(currentPage()); setMobileOpen(false); };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  useEffect(() => {
    if (pendingProject.current) {
      if (projects.data?.some(item => item.id === pendingProject.current)) pendingProject.current = null;
      else return;
    }
    if (project && project.id !== projectId) setProjectId(project.id);
  }, [project, projectId, projects.data]);
  useEffect(() => { if (projectId) localStorage.setItem('tervik_project', projectId); setClusterId(null); setConversationId(null); }, [projectId]);
  useEffect(() => { document.title = `${page === 'welcome' ? 'Agent intelligence' : titles[page]} — Tervik`; }, [page]);
  const navigate = (next: Page) => { window.location.hash = next; setPage(next); setMobileOpen(false); };
  const selectConversation = (id: string) => { setClusterId(null); setConversationId(id); };
  const seedDemo = async () => {
    setDemoBusy(true); setActionError('');
    try { const result = await request<{ project_id: string }>('/api/demo/seed', { method: 'POST' }); pendingProject.current = result.project_id; setProjectId(result.project_id); setRefresh(value => value + 1); navigate('overview'); }
    catch (cause) { setActionError((cause as Error).message); } finally { setDemoBusy(false); }
  };
  const modalClose = () => { setCreateOpen(false); setProjectName(''); setCreateError(''); };
  const noProject = <div className="panel no-project-panel"><EmptyState icon={Layers3} title="A clearer view of your agents starts here." description="Create your first project to connect an agent, or explore a sample workspace to see how Tervik works."><button className="button button-primary" onClick={() => setCreateOpen(true)}><Plus size={16} />Create your first project</button><button className="button button-secondary" disabled={demoBusy} onClick={seedDemo}>{demoBusy ? <LoaderCircle size={15} className="spin" /> : <Layers3 size={16} />}Explore sample workspace</button></EmptyState></div>;
  const navItems: { page: Page; icon: LucideIcon; label: string }[] = [{ page: 'overview', icon: LayoutDashboard, label: 'Overview' }, { page: 'failures', icon: Layers3, label: 'Failure clusters' }, { page: 'discovery', icon: Sparkles, label: 'Discovery' }, { page: 'conversations', icon: MessageSquare, label: 'Conversations' }];
  return <>
    {page === 'welcome' ? <><Welcome onStart={() => navigate('overview')} onDemo={seedDemo} demoBusy={demoBusy} />{actionError && <div className="welcome-error"><ErrorState message={actionError} onRetry={seedDemo} /></div>}</> : <div className="app-shell">
      {mobileOpen && <button className="sidebar-scrim" onClick={() => setMobileOpen(false)} aria-label="Close navigation" />}
      <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}><Logo /><div className="workspace-label">WORKSPACE</div><div className="project-picker"><span className="project-avatar">{project?.name.slice(0, 1).toUpperCase() || 'T'}</span><select aria-label="Select project" value={project?.id || ''} onChange={event => setProjectId(event.target.value)}>{projects.data?.length ? projects.data.map(item => <option key={item.id} value={item.id}>{item.name}{item.is_demo ? ' (sample)' : ''}</option>) : <option value="">No projects yet</option>}</select><ChevronDown size={13} /><button onClick={() => setCreateOpen(true)} aria-label="Create project" title="Create project"><Plus size={15} /></button></div>
        <nav className="main-nav" aria-label="Main navigation">{navItems.map(({ page: navPage, icon: Icon, label }) => <a href={`#${navPage}`} key={navPage} className={page === navPage ? 'active' : ''} aria-current={page === navPage ? 'page' : undefined}><Icon size={18} /><span>{label}</span>{navPage === 'failures' && !!overview.data?.top_clusters.length && <span className="nav-count">{overview.data.top_clusters.length}</span>}</a>)}</nav><div className="nav-divider" /><nav className="secondary-nav"><a href="#integration" className={page === 'integration' ? 'active' : ''}><Code2 size={18} /><span>Integration</span>{page !== 'integration' && <span className="new-badge">SETUP</span>}</a><a href="#welcome"><CircleHelp size={18} /><span>Getting started</span><ArrowUpRight size={14} /></a></nav>
        <div className="sidebar-bottom"><div className="sidebar-tip"><span><Sparkles size={17} /></span><strong>A better next turn.</strong><p>Your users are showing you what to improve. Follow the signals.</p><button onClick={() => navigate('integration')}>Connect an agent<ArrowRight size={14} /></button></div><button className="settings-button" onClick={() => { setAdminToken(sessionStorage.getItem('tervik_admin_token') || ''); setSessionToken(sessionStorage.getItem('tervik_session') || ''); setSettingsOpen(true); }}><Settings2 size={17} /><span>Connection settings</span></button><div className="workspace-footer"><span className="user-avatar">T</span><span><strong>Local workspace</strong><small>Development foundation</small></span><span className="local-dot" /></div></div>
      </aside>
      <div className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Open navigation"><Menu size={20} /></button><span>Workspace</span><ChevronRight size={12} /><strong>{project?.name || 'Getting started'}</strong>{project?.is_demo && <span className="demo-badge">SAMPLE DATA</span>}</div><div className="topbar-right"><span className={`api-health ${health.data ? 'connected' : ''}`}><span />{health.data ? 'API connected' : health.loading ? 'Connecting' : 'API offline'}</span><button className="topbar-icon" onClick={() => navigate('integration')} aria-label="Open integration guide" title="Integration guide"><FileCode2 size={18} /></button></div></header>
        <main className="main-content"><div className="page-heading"><div><div className="page-eyebrow">AGENT INTELLIGENCE</div><h1>{titles[page]}</h1><p>{page === 'overview' ? 'Know what’s working. See what needs a closer look.' : page === 'failures' ? 'The moments that deserve your attention, connected to the evidence.' : page === 'discovery' ? 'What users are trying to accomplish, grouped with evidence.' : page === 'conversations' ? 'A closer look at what your users and agents are saying.' : 'A few small steps between your agent and its next insight.'}</p></div>{page !== 'integration' && <div className="heading-actions"><label className="date-range"><Clock3 size={15} /><select aria-label="Date range" value={range} onChange={event => setRange(event.target.value as Range)}>{Object.entries(rangeLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><ChevronDown size={13} /></label><button className="button button-primary heading-connect" onClick={() => project ? navigate('integration') : setCreateOpen(true)}><Plus size={15} />{project ? 'Connect agent' : 'New project'}</button></div>}</div>
          {actionError && <div className="action-error"><TriangleAlert size={16} /><span>{actionError}</span><button className="icon-button" onClick={() => setActionError('')} aria-label="Dismiss error"><X size={15} /></button></div>}
          {projects.loading ? <Loading /> : projects.error ? <ErrorState message={projects.error} onRetry={projects.retry} /> : !project ? noProject : page === 'overview' ? <OverviewPage {...overview} range={range} onPage={navigate} onCluster={setClusterId} onConversation={selectConversation} onDemo={seedDemo} demoBusy={demoBusy} /> : page === 'failures' ? <FailuresPage projectId={project.id} range={range} refresh={refresh} onSelect={setClusterId} /> : page === 'discovery' ? <DiscoveryPage projectId={project.id} range={range} refresh={refresh} onConversation={selectConversation} /> : page === 'conversations' ? <ConversationsPage projectId={project.id} range={range} refresh={refresh} onSelect={selectConversation} /> : <IntegrationPage key={project.id} project={project} refresh={refresh} />}
          <footer className="dashboard-footer"><span>Tervik<span className="footer-separator">/</span>Find failures. Build better agents.</span><span><span className="pulse-dot" />Rule-based analysis</span></footer>
        </main>
      </div>
    </div>}
    {clusterId && <ClusterDrawer key={clusterId} id={clusterId} range={range} onClose={() => setClusterId(null)} onConversation={selectConversation} onChanged={() => setRefresh(value => value + 1)} />}
    {conversationId && <ConversationDrawer key={conversationId} id={conversationId} onClose={() => setConversationId(null)} />}
    {createOpen && <Modal title="Create a project" onClose={modalClose}><form className="modal-body" onSubmit={async event => {
      event.preventDefault(); if (!projectName.trim()) return;
      setCreateBusy(true); setCreateError('');
      try { const result = await request<Project>('/api/projects', { method: 'POST', body: JSON.stringify({ name: projectName.trim() }) }); pendingProject.current = result.id; setProjectId(result.id); setRefresh(value => value + 1); modalClose(); navigate('integration'); }
      catch (cause) { setCreateError((cause as Error).message); } finally { setCreateBusy(false); }
    }}><span className="modal-feature-icon"><FolderPlus size={26} /></span><h2>A home for your agent.</h2><p>Keep its conversations, failure signals, and integration key together in a project.</p><label className="field-label" htmlFor="project-name">Project name</label><input id="project-name" className="text-field" placeholder="e.g. Customer support agent" value={projectName} onChange={event => setProjectName(event.target.value)} required maxLength={80} autoComplete="off" />{createError && <p className="inline-error">{createError}</p>}<div className="modal-actions"><button type="button" className="button button-secondary" onClick={modalClose}>Cancel</button><button type="submit" className="button button-primary" disabled={createBusy || !projectName.trim()}>{createBusy ? <LoaderCircle size={16} className="spin" /> : <Plus size={16} />}Create project</button></div></form></Modal>}
    {settingsOpen && <Modal title="Connection settings" onClose={() => setSettingsOpen(false)}><form className="modal-body" onSubmit={event => { event.preventDefault(); if (sessionToken.trim()) sessionStorage.setItem('tervik_session', sessionToken.trim()); else sessionStorage.removeItem('tervik_session'); if (adminToken.trim()) sessionStorage.setItem('tervik_admin_token', adminToken.trim()); else sessionStorage.removeItem('tervik_admin_token'); setRefresh(value => value + 1); setSettingsOpen(false); }}><span className="modal-feature-icon"><Settings2 size={25} /></span><h2>Your local connection.</h2><p>The dashboard connects through its API proxy. Sign in with an account session, or add the administrator token if the service requires it.</p><label className="field-label" htmlFor="session-token">Account session</label><input id="session-token" className="text-field" type="password" placeholder="Sign in via the API to get a session" value={sessionToken} onChange={event => setSessionToken(event.target.value)} autoComplete="off" /><label className="field-label" htmlFor="admin-token">Administrator token</label><input id="admin-token" className="text-field" type="password" placeholder="Optional in local developer mode" value={adminToken} onChange={event => setAdminToken(event.target.value)} autoComplete="off" /><p className="field-hint">Stored for this browser session only. This is separate from a project’s ingestion key.</p><div className="connection-details"><span>API status<strong>{health.data ? 'Connected' : 'Unavailable'}</strong></span><span>Storage<strong>{health.data?.storage || '—'}</strong></span><span>Analysis<strong>{health.data?.analysis_mode || 'Rule-based'}</strong></span></div><div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => { setAdminToken(''); setSessionToken(''); }}>Clear tokens</button><button type="submit" className="button button-primary"><Check size={16} />Save connection</button></div></form></Modal>}
  </>;
}
