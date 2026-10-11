import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowUp, Bot, LoaderCircle, MessageSquare, Plus, TriangleAlert, Wrench, X } from 'lucide-react';
import { request } from './api';
import { failureLabel } from './labels';
import type { ConversationDetail, Event, PlaygroundChat, PlaygroundReply, PlaygroundStatus, Signal } from './types';

type Turn = { key: string; user?: Event; assistant?: Event; tools: Event[]; signals: Signal[] };

/** Group a conversation's messages into turns: a user message, the agent's
 * reply, the tool calls made between them, and the problems found in any of them. */
function toTurns(detail: ConversationDetail | null): Turn[] {
  if (!detail) return [];
  const turns: Turn[] = [];
  const byKey = new Map<string, Turn>();
  const keyOf = new Map<string, string>();
  let current: Turn | null = null;
  for (const message of detail.messages) {
    let key = message.trace_id || '';
    if (!key || (message.role === 'user' && byKey.has(key) && byKey.get(key)!.user)) {
      // Untraced messages: a user message starts a new turn; others join the latest one.
      key = message.role === 'user' || !current ? `turn-${message.id}` : current.key;
    }
    let turn = byKey.get(key);
    if (!turn) {
      turn = { key, tools: [], signals: [] };
      byKey.set(key, turn);
      turns.push(turn);
    }
    if (message.role === 'user') turn.user = message;
    else if (message.role === 'assistant') turn.assistant = message;
    else if (message.role === 'tool') turn.tools.push(message);
    keyOf.set(message.id, key);
    current = turn;
  }
  for (const signal of detail.signals) byKey.get(keyOf.get(signal.event_id) || '')?.signals.push(signal);
  return turns;
}

function toolArgs(tool: Event) {
  const input = tool.metadata?.input;
  if (typeof input !== 'string' || !input) return '';
  try {
    const parsed = JSON.parse(input);
    return parsed && typeof parsed === 'object' ? Object.values(parsed).map(v => typeof v === 'string' ? v : JSON.stringify(v)).join(', ') : String(parsed);
  } catch { return input; }
}

/** Plain text with fenced code blocks. */
function Reply({ text }: { text: string }) {
  const parts = text.split(/```[\w-]*\n?([\s\S]*?)```/g);
  return <div className="chat-text">{parts.map((part, index) => index % 2
    ? <pre key={index}><code>{part.replace(/\n$/, '')}</code></pre>
    : part.trim() && <p key={index}>{part.trim()}</p>)}</div>;
}

export function ChatPage({ projectId, refresh, onConversation }: { projectId: string; refresh: number; onConversation: (id: string) => void }) {
  const [status, setStatus] = useState<PlaygroundStatus | null>(null);
  const [statusError, setStatusError] = useState('');
  const [chats, setChats] = useState<PlaygroundChat[]>([]);
  const [active, setActive] = useState<{ session_id: string; conversation_id: string } | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [persona, setPersona] = useState('general');
  const [model, setModel] = useState('');
  const [input, setInput] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const [focus, setFocus] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let alive = true;
    request<PlaygroundStatus>('/api/playground/status')
      .then(result => { if (!alive) return; setStatus(result); setStatusError(''); setModel(value => result.models.some(m => m.id === value) ? value : result.default_model || ''); })
      .catch(cause => { if (alive) setStatusError((cause as Error).message); });
    return () => { alive = false; };
  }, [refresh]);
  useEffect(() => {
    let alive = true;
    request<PlaygroundChat[]>(`/api/projects/${encodeURIComponent(projectId)}/playground/chats`).then(rows => { if (alive) setChats(rows); }).catch(() => {});
    return () => { alive = false; };
  }, [projectId, refresh, tick]);
  useEffect(() => { setActive(null); setDetail(null); setError(''); }, [projectId]);
  // The open chat refreshes with the dashboard, so new problems appear on their own.
  useEffect(() => {
    if (!active) return;
    let alive = true;
    request<ConversationDetail>(`/api/conversations/${encodeURIComponent(active.conversation_id)}`).then(result => { if (alive) setDetail(result); }).catch(() => {});
    return () => { alive = false; };
  }, [active, refresh]);
  useEffect(() => { const thread = threadRef.current; if (thread && !focus) thread.scrollTop = thread.scrollHeight; }, [detail?.messages.length, pending, error, focus]);
  useEffect(() => {
    if (!focus) return;
    const thread = threadRef.current, turn = document.getElementById(`chat-${focus}`);
    // Scroll the thread only, so the page itself stays put.
    if (thread && turn) thread.scrollTo({ top: turn.getBoundingClientRect().top - thread.getBoundingClientRect().top + thread.scrollTop - 12, behavior: 'smooth' });
    const timer = window.setTimeout(() => setFocus(null), 1800);
    return () => window.clearTimeout(timer);
  }, [focus]);

  const personaInfo = status?.personas.find(item => item.id === persona);
  const turns = toTurns(detail);
  const problemGroups = Array.from((detail?.signals || []).reduce((groups, signal) => groups.set(signal.kind, [...(groups.get(signal.kind) || []), signal]), new Map<string, Signal[]>()));
  const ready = Boolean(model) && !pending;

  const openChat = (chat: PlaygroundChat) => {
    setActive({ session_id: chat.session_id, conversation_id: chat.conversation_id });
    setPersona(chat.persona);
    setDetail(null); setError(''); inputRef.current?.focus();
  };
  const newChat = () => { setActive(null); setDetail(null); setError(''); setInput(''); inputRef.current?.focus(); };
  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || !ready) return;
    setPending(text); setError(''); setInput('');
    try {
      const reply = await request<PlaygroundReply>(`/api/projects/${encodeURIComponent(projectId)}/playground/chat`, {
        method: 'POST', body: JSON.stringify({ message: text, session_id: active?.session_id ?? null, persona, model }),
      });
      const fresh = await request<ConversationDetail>(`/api/conversations/${encodeURIComponent(reply.conversation_id)}`);
      setDetail(fresh);
      setActive(previous => previous?.session_id === reply.session_id ? previous : { session_id: reply.session_id, conversation_id: reply.conversation_id });
      setTick(value => value + 1);
    } catch (cause) {
      setError((cause as Error).message); setInput(text);
    } finally {
      setPending(null); inputRef.current?.focus();
    }
  };
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(input); }
  };

  return <section className="chat-shell panel">
    <aside className="chat-list" aria-label="Chats">
      <button className="chat-new" onClick={newChat}><Plus size={15} />New chat</button>
      {chats.length > 0 && <p className="chat-list-label">Your chats</p>}
      {chats.map(chat => <button key={chat.session_id} className={`chat-item ${active?.session_id === chat.session_id ? 'active' : ''}`} onClick={() => openChat(chat)} title={chat.problems.length ? chat.problems.map(failureLabel).join(', ') : 'No problems found'}>
        <span>{chat.title}</span>{chat.problems.length > 0 && <em><TriangleAlert size={11} />{chat.problems.length}</em>}
      </button>)}
    </aside>

    <div className="chat-main">
      <div className="chat-toolbar">
        <label className="chat-select"><span>Agent</span><select aria-label="Agent" value={persona} onChange={event => setPersona(event.target.value)}>{(status?.personas || []).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="chat-select"><span>Model</span><select aria-label="Model" value={model} onChange={event => setModel(event.target.value)} disabled={!status?.models.length}>{status?.models.length ? status.models.map(item => <option key={item.id} value={item.id}>{item.label}</option>) : <option value="">No model available</option>}</select></label>
        {active && <button className="text-button chat-open" onClick={() => onConversation(active.conversation_id)}><MessageSquare size={14} />Open in Conversations</button>}
      </div>
      {(status?.note || statusError) && !status?.models.length && <div className="chat-note"><TriangleAlert size={15} /><span>{statusError || status?.note}</span></div>}
      {problemGroups.length > 0 && <div className="signal-summary chat-problems"><TriangleAlert size={17} /><div><strong>{detail!.signals.length} {detail!.signals.length === 1 ? 'problem' : 'problems'} found in this chat</strong><span className="signal-jumps">{problemGroups.map(([kind, signals]) => {
        const turn = turns.find(item => item.signals.some(signal => signal.id === signals[0].id));
        return <button key={kind} onClick={() => turn && setFocus(turn.key)}>{failureLabel(kind)}{signals.length > 1 ? ` ×${signals.length}` : ''}</button>;
      })}</span></div></div>}

      <div className="chat-thread" ref={threadRef}>
        {!turns.length && !pending ? <div className="chat-empty">
          <h2>Chat with your agent.</h2>
          <p>{personaInfo?.description || 'Ask anything.'} Every reply is checked for problems the moment it lands.</p>
          <div className="chat-ideas">{(personaInfo?.ideas || []).map(idea => <button key={idea} onClick={() => void send(idea)} disabled={!ready}>{idea}</button>)}</div>
        </div> : <div className="chat-turns">
          {turns.map(turn => <div key={turn.key} id={`chat-${turn.key}`} className={`chat-turn ${focus === turn.key ? 'chat-focus' : ''}`}>
            {turn.user && <div className="chat-user"><p>{turn.user.content}</p></div>}
            {(turn.assistant || turn.tools.length > 0) && <div className="chat-agent"><span className="chat-avatar"><Bot size={15} /></span><div className="chat-body">
              {turn.assistant && <Reply text={turn.assistant.content} />}
              {turn.tools.length > 0 && <div className="chat-tools">{turn.tools.map(tool => <span key={tool.id} className={`chat-tool ${tool.status === 'error' ? 'failed' : ''}`} title={tool.content}>{tool.status === 'error' ? <X size={12} /> : <Wrench size={12} />}{tool.name}({toolArgs(tool)}){tool.status === 'error' ? ' failed' : ''}</span>)}</div>}
              {turn.signals.length > 0
                ? <div className="chat-failures">{turn.signals.map(signal => <div key={signal.id} className="chat-failure"><TriangleAlert size={13} /><span><strong>{failureLabel(signal.kind)}.</strong> {signal.reason}</span></div>)}</div>
                : <div className="chat-clean">No problems found in this turn</div>}
            </div></div>}
          </div>)}
          {pending && <div className="chat-turn"><div className="chat-user"><p>{pending}</p></div><div className="chat-agent"><span className="chat-avatar"><Bot size={15} /></span><div className="chat-typing" aria-label="Waiting for the reply"><span /><span /><span /></div></div></div>}
          {error && <div className="chat-error"><TriangleAlert size={15} /><span>{error}</span></div>}
        </div>}
      </div>

      <form className="chat-composer" onSubmit={event => { event.preventDefault(); void send(input); }}>
        <div className="chat-box">
          <textarea ref={inputRef} rows={1} value={input} placeholder={model ? 'Message the agent' : 'Start a model to chat'} aria-label="Message"
            onChange={event => { setInput(event.target.value); event.target.style.height = 'auto'; event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`; }} onKeyDown={onKey} />
          <button type="submit" className="chat-send" disabled={!ready || !input.trim()} aria-label="Send">{pending ? <LoaderCircle size={16} className="spin" /> : <ArrowUp size={16} />}</button>
        </div>
        <p>Chats are saved to this project and checked like your agent’s real conversations.</p>
      </form>
    </div>
  </section>;
}
