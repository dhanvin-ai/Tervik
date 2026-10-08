import { useState, useEffect } from 'react';
import { Zap, ShieldCheck, MessageSquare, Layers3, GitBranch, Code2, ArrowRight, Check } from 'lucide-react';
import { useScrollReveal } from '../hooks/useMotion';

export function FeaturesMotionGrid() {
  const { ref, isRevealed } = useScrollReveal(0.15);
  const [tickerIndex, setTickerIndex] = useState(0);

  // Autoscroll event ticker in the Evidence Clusters card
  useEffect(() => {
    const interval = setInterval(() => {
      setTickerIndex(prev => (prev + 1) % 4);
    }, 2800);
    return () => clearInterval(interval);
  }, []);

  const TICKER_ITEMS = [
    { id: '#corr-82', role: 'User', text: 'No, that is the wrong billing address', type: 'correction' },
    { id: '#tool-14', role: 'Agent', text: 'Error: Database connection timed out (504)', type: 'tool_error' },
    { id: '#loop-09', role: 'Agent', text: 'Retrying stripe_charge attempt 3/3', type: 'repetition' },
    { id: '#phr-33', role: 'Agent', text: 'Notice: As an AI model I cannot assist', type: 'forbidden' },
  ];

  return (
    <div ref={ref} className={`m-bento-grid ${isRevealed ? 'is-revealed' : ''}`}>
      {/* 1. Sub-2ms Ingestion with SVG Chart Drawing */}
      <div className="m-bento-card bento-card-chart">
        <div className="m-bento-icon"><Zap size={18} /></div>
        <div className="m-bento-content">
          <div className="m-bento-card-head">
            <h3>Sub-2ms Ingestion</h3>
            <span className="m-bento-badge text-emerald-400">1.8ms avg</span>
          </div>
          <p>Non-blocking asynchronous event batching. Zero latency added to agent generation loops or tool executions.</p>

          {/* SVG Animated Chart Drawing */}
          <div className="m-bento-chart-box">
            <svg viewBox="0 0 240 50" className="m-bento-chart-svg">
              <path
                d="M 10 40 L 40 38 L 70 35 L 100 22 L 130 18 L 160 20 L 190 12 L 230 14"
                fill="none"
                stroke="rgba(168, 85, 247, 0.2)"
                strokeWidth="4"
              />
              <path
                d="M 10 40 L 40 38 L 70 35 L 100 22 L 130 18 L 160 20 L 190 12 L 230 14"
                fill="none"
                stroke="#a855f7"
                strokeWidth="2"
                className="m-chart-draw-line"
              />
              <circle cx="230" cy="14" r="3.5" fill="#34d399" className="m-chart-pulse-point" />
            </svg>
            <div className="m-bento-chart-footer">
              <span>Async flush</span>
              <span className="text-zinc-500">200 events / batch</span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Deterministic Guardrails with Branching Path Tracing */}
      <div className="m-bento-card bento-card-branch">
        <div className="m-bento-icon"><ShieldCheck size={18} /></div>
        <div className="m-bento-content">
          <div className="m-bento-card-head">
            <h3>Deterministic Guardrails</h3>
            <span className="status status-healthy"><span />Regex Engine</span>
          </div>
          <p>No fuzzy judge models that hallucinate. Transparent regex patterns, required tools, and failure thresholds.</p>

          {/* Branching Path Tracing Graphic */}
          <div className="m-bento-branch-box">
            <svg viewBox="0 0 240 55" className="m-bento-branch-svg">
              {/* Main Line */}
              <path d="M 10 28 L 75 28" stroke="rgba(255,255,255,0.2)" strokeWidth="2" />
              {/* Branch 1 (Pass) */}
              <path d="M 75 28 C 110 28, 130 14, 170 14 L 230 14" stroke="#34d399" strokeWidth="2" className="m-branch-path-pass" />
              {/* Branch 2 (Flagged) */}
              <path d="M 75 28 C 110 28, 130 42, 170 42 L 230 42" stroke="#ef4444" strokeWidth="2" strokeDasharray="3 3" className="m-branch-path-flag" />
              {/* Nodes */}
              <circle cx="75" cy="28" r="4" fill="#a855f7" />
              <circle cx="230" cy="14" r="4" fill="#34d399" />
              <circle cx="230" cy="42" r="4" fill="#ef4444" />
            </svg>
            <div className="m-bento-branch-labels">
              <span className="text-emerald-400">Normal Flow</span>
              <span className="text-rose-400">Rule Intercept</span>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Evidence-Backed Clusters with Internal Autoscroll Ticker */}
      <div className="m-bento-card bento-card-ticker">
        <div className="m-bento-icon"><MessageSquare size={18} /></div>
        <div className="m-bento-content">
          <div className="m-bento-card-head">
            <h3>Evidence-Backed Clusters</h3>
            <span className="m-bento-badge">Real-Time Citations</span>
          </div>
          <p>Every cluster cites exact conversation excerpts, user IDs, and timestamps. Never guess why an agent stumbled.</p>

          {/* Internal Autoscrolling Ticker Box */}
          <div className="m-bento-ticker-box">
            <div
              className="m-bento-ticker-stream"
              style={{ transform: `translateY(-${tickerIndex * 38}px)` }}
            >
              {TICKER_ITEMS.map((item, idx) => (
                <div key={idx} className={`m-ticker-item type-${item.type}`}>
                  <span className="m-ticker-tag">{item.id}</span>
                  <span className="m-ticker-role">{item.role}:</span>
                  <span className="m-ticker-text">{item.text}</span>
                  <ArrowRight size={11} className="m-ticker-arrow" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 4. Universal Compatibility with Rotating Ring Highlights */}
      <div className="m-bento-card bento-card-rings">
        <div className="m-bento-icon"><Code2 size={18} /></div>
        <div className="m-bento-content">
          <div className="m-bento-card-head">
            <h3>Universal Compatibility</h3>
            <span className="m-bento-badge text-sky-400">SDK + Skills</span>
          </div>
          <p>Drop-in skill and TypeScript SDK. Works with Claude Code, Cursor, OpenCode, Codex, Devin, and custom frameworks.</p>

          {/* Stationary Logos with Rotating Highlight Rings */}
          <div className="m-bento-logos-ring-row">
            {['Claude', 'Cursor', 'OpenCode', 'Codex', 'Devin'].map((name, i) => (
              <div key={name} className="m-ring-logo-wrapper">
                <svg viewBox="0 0 44 44" className="m-ring-svg">
                  <circle cx="22" cy="22" r="18" className={`m-rotating-ring ring-${i % 3}`} />
                </svg>
                <span className="m-ring-logo-text">{name.slice(0, 2)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 5. Candidate Replay Evals */}
      <div className="m-bento-card">
        <div className="m-bento-icon"><GitBranch size={18} /></div>
        <div className="m-bento-content">
          <div className="m-bento-card-head">
            <h3>Candidate Replay Evals</h3>
            <span className="m-bento-badge text-emerald-400">Zero Regressions</span>
          </div>
          <p>Evaluate prompt or tool adjustments across historical production failures before deploying changes to live users.</p>
          <div className="m-eval-bar-wrapper">
            <div className="m-eval-bar-meta">
              <span>Candidate Run #48</span>
              <span className="text-emerald-400 font-mono">98.2% Pass</span>
            </div>
            <div className="m-eval-track">
              <div className="m-eval-fill" style={{ width: '98.2%' }} />
            </div>
          </div>
        </div>
      </div>

      {/* 6. Local & Self-Hosted */}
      <div className="m-bento-card">
        <div className="m-bento-icon"><Layers3 size={18} /></div>
        <div className="m-bento-content">
          <div className="m-bento-card-head">
            <h3>Local &amp; Self-Hosted</h3>
            <span className="status status-healthy"><span />Air-Gapped</span>
          </div>
          <p>Runs locally or self-hosted with SQLite or PostgreSQL. Your customer conversations never leave your infrastructure.</p>
          <div className="m-bento-tags-row">
            <span className="m-pill-tag"><Check size={11} /> SQLite</span>
            <span className="m-pill-tag"><Check size={11} /> PostgreSQL</span>
            <span className="m-pill-tag"><Check size={11} /> Docker ready</span>
          </div>
        </div>
      </div>
    </div>
  );
}
