export type Range = '24h' | '7d' | '30d';
export type Page = 'overview' | 'failures' | 'conversations' | 'integration' | 'welcome';
export interface Project {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  is_demo: boolean;
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
