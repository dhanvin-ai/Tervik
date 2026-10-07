export type Range = '24h' | '7d' | '30d';
export type Page = 'overview' | 'failures' | 'discovery' | 'conversations' | 'integration' | 'welcome';
export interface Project {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  is_demo: boolean;
  org_id?: string;
}
export interface SetupStatus {
  project: Project;
  key_configured: boolean;
  active_credentials: number;
  events_received: number;
  conversations: number;
  last_event_at: string | null;
  jobs: { pending: number; processed: number; failed: number; dead: number; expired: number };
  usage_events: number;
  capture: { capture_content: boolean; retention_days: number };
}
export interface Cluster {
  id: string;
  project_id: string;
  title: string;
  description: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  kind: string;
  status: 'open' | 'resolved';
  count: number;
  affected_users: number;
  share: number;
  trend: number;
  created_at: string;
  last_seen: string;
  suggested_fix: string;
  detector_version: string;
  rule_version: string;
}
export interface Conversation {
  id: string;
  project_id: string;
  user_id: string | null;
  started_at: string;
  last_at: string;
  message_count: number;
  latency_ms: number;
  status: 'healthy' | 'flagged';
  tags: string[];
  preview: string;
  model: string | null;
  cost_usd: number;
}
export interface Event {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'tool' | 'system';
  content: string;
  timestamp: string;
  name?: string;
  status?: string;
  model?: string;
  latency_ms?: number;
  tokens?: number;
}
export interface Signal {
  id: string;
  event_id: string;
  conversation_id: string;
  kind: string;
  reason: string;
  severity: string;
  detector_version: string;
  rule_version: string;
}
export interface BehaviorRule {
  id: string;
  project_id: string;
  name: string;
  kind: 'forbidden_phrase' | 'required_tool';
  pattern: string | null;
  tool: string | null;
  severity: 'critical' | 'high' | 'medium' | 'low';
  enabled: boolean;
  version: string;
  created_at: string;
}
export interface DiscoveryIntent {
  id: string;
  project_id: string;
  name: string;
  description: string;
  examples: string[];
  enabled: boolean;
  version: string;
  created_at: string;
}
export interface DiscoveryCluster {
  id: string;
  key: string;
  label: string;
  status: string;
  count: number;
  affected_users: number;
  evidence: { conversation_id: string; excerpt: string; reason: string }[];
  members: string[];
  detector_version: string;
}
export interface Discovery {
  project: Project;
  clusters: DiscoveryCluster[];
  intents: { intent_id: string; intent_name: string; conversations: number; sample: string[] }[];
  coverage: {
    conversations_total: number;
    conversations_analyzed: number;
    messages_total: number;
    users_total: number;
    clustered: number;
    unassigned: number;
  };
}
export interface AlertRule {
  id: string;
  project_id: string;
  name: string;
  kind: 'threshold' | 'trend' | 'summary';
  signal_kind: string | null;
  threshold: number;
  window_hours: number;
  min_samples: number;
  cooldown_hours: number;
  channels: { type: string; configured: boolean }[];
  enabled: boolean;
  state: string;
  last_fired_at: string | null;
  resolved_at: string | null;
}
export interface Delivery {
  id: string;
  rule_id: string;
  state: string;
  attempts: number;
  channel_type: string;
  title: string;
  error_code: string | null;
  sent_at: string | null;
  created_at: string;
}
export interface EvalDataset {
  id: string;
  project_id: string;
  name: string;
  version: string;
  status: 'draft' | 'reviewed' | 'approved';
  cases: { id: string; input: string }[];
  case_count: number;
  created_at: string;
}
export interface EvalRun {
  id: string;
  dataset_id: string;
  project_id: string;
  baseline: { name: string; version: string };
  candidate: { name: string; version: string };
  repeats: number;
  state: string;
  results: {
    cases: number;
    repeats: number;
    reproducible: boolean;
    baseline_pass: number;
    candidate_pass: number;
    fixed: string[];
    regressed: string[];
    baseline_violations: number;
    candidate_violations: number;
    verdict: string;
  };
  created_at: string;
}
export interface Span {
  id: string;
  parent_id: string | null;
  name: string;
  kind: string;
  status: string;
  duration_ms: number;
  input: unknown;
  output: unknown;
}
export interface ConversationDetail extends Conversation {
  messages: Event[];
  signals: Signal[];
  spans: Span[];
}
export interface ClusterDetail extends Cluster {
  conversations: Conversation[];
  evidence: { event_id: string; conversation_id: string; content: string; reason: string }[];
}
export interface Overview {
  project: Project;
  metrics: {
    conversations: number;
    messages: number;
    failure_rate: number;
    affected_users: number;
    avg_latency_ms: number;
    cost_usd: number;
  };
  trend: { date: string; conversations: number; failures: number }[];
  top_clusters: Cluster[];
  recent_conversations: Conversation[];
  analysis_mode: string;
}
