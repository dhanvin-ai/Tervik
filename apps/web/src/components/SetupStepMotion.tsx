import { useState, useEffect } from 'react';
import { Check, Copy, Network } from 'lucide-react';
import { useScrollReveal, usePrefersReducedMotion } from '../hooks/useMotion';

const INSTALL_COMMAND = 'npx skills add dhanvin-ai/tervik --skill tervik';
const INSTALL_PROMPT = 'Use the tervik skill to add Tervik analytics to this agent.';

interface SetupStepMotionProps {
  onCopy: () => void;
  copied: boolean;
}

export function SetupStepMotion({ onCopy, copied }: SetupStepMotionProps) {
  const [activeStep, setActiveStep] = useState<1 | 2 | 3>(1);
  const [typedLines, setTypedLines] = useState<number>(1);
  const prefersReduced = usePrefersReducedMotion();
  const { ref, isRevealed } = useScrollReveal(0.2);

  // Auto-advance terminal typing lines for cinematic synchronization
  useEffect(() => {
    if (prefersReduced) {
      setTypedLines(5);
      return;
    }
    setTypedLines(1);
    const t1 = setTimeout(() => setTypedLines(2), 250);
    const t2 = setTimeout(() => setTypedLines(3), 550);
    const t3 = setTimeout(() => setTypedLines(4), 850);
    const t4 = setTimeout(() => setTypedLines(5), 1150);

    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
    };
  }, [activeStep, prefersReduced]);

  return (
    <div ref={ref} className={`m-setup-motion-wrapper ${isRevealed ? 'is-revealed' : ''}`}>
      {/* 3 Step Stack Tabs with subtle rotation and stacking */}
      <div className="m-setup-stack-nav">
        {[
          { id: 1, label: '01 · Install Skill', badge: '10 SECONDS' },
          { id: 2, label: '02 · Prompt Agent', badge: 'AGENT AUTONOMOUS' },
          { id: 3, label: '03 · Live Ingestion', badge: 'LOCAL-FIRST' },
        ].map(step => (
          <button
            key={step.id}
            className={`m-setup-step-card ${activeStep === step.id ? 'active-step' : ''}`}
            onClick={() => setActiveStep(step.id as any)}
          >
            <div className="m-setup-step-head">
              <span className="m-setup-num">0{step.id}</span>
              <span className="m-setup-badge">{step.badge}</span>
            </div>
            <div className="m-setup-step-name">{step.label}</div>
          </button>
        ))}
      </div>

      {/* Synchronized Terminal & Node Graph Telemetry Stage */}
      <div className="m-setup-stage">
        {/* Left: Interactive Terminal with typing & blinking caret */}
        <div className="m-setup-terminal-card">
          <div className="m-terminal-top">
            <div className="m-window-dots">
              <span className="m-dot m-dot-red" />
              <span className="m-dot m-dot-yellow" />
              <span className="m-dot m-dot-green" />
            </div>
            <span className="m-terminal-title">zsh — local agent workspace</span>
            <button
              className="icon-button m-terminal-copy"
              onClick={onCopy}
              aria-label="Copy active setup command"
              title="Copy to clipboard"
            >
              {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
            </button>
          </div>

          <div className="m-terminal-screen">
            {activeStep === 1 && (
              <div className="m-term-body">
                <div className="m-term-line">
                  <span className="m-term-prompt">$</span> {INSTALL_COMMAND}
                  <span className="m-term-caret" />
                </div>
                {typedLines >= 2 && <div className="m-term-out text-zinc-400">Fetching skill definition from dhanvin-ai/tervik...</div>}
                {typedLines >= 3 && <div className="m-term-out text-emerald-400">✔ Added skill &quot;tervik&quot; to current workspace</div>}
                {typedLines >= 4 && <div className="m-term-out text-zinc-500">Skill location: .agents/skills/tervik/SKILL.md</div>}
                {typedLines >= 5 && <div className="m-term-out text-zinc-300">Ready for autonomous agent prompt execution.</div>}
              </div>
            )}

            {activeStep === 2 && (
              <div className="m-term-body">
                <div className="m-term-line">
                  <span className="m-term-prompt">&gt;</span> {INSTALL_PROMPT}
                  <span className="m-term-caret" />
                </div>
                {typedLines >= 2 && <div className="m-term-out text-zinc-400">Agent reading skill instructions from .agents/skills/tervik/SKILL.md...</div>}
                {typedLines >= 3 && <div className="m-term-out text-emerald-400">✔ Integrated @tervik/sdk non-blocking client</div>}
                {typedLines >= 4 && <div className="m-term-out text-emerald-400">✔ Attached conversation turns &amp; tool execution hooks</div>}
                {typedLines >= 5 && <div className="m-term-out text-zinc-500">Ready. Zero latency overhead added to generation loops.</div>}
              </div>
            )}

            {activeStep === 3 && (
              <div className="m-term-body">
                <div className="m-term-line">
                  <span className="m-term-prompt">$</span> node scripts/dev.mjs
                  <span className="m-term-caret" />
                </div>
                {typedLines >= 2 && <div className="m-term-out text-zinc-400">Ingestion API listening on http://127.0.0.1:8000 (SQLite storage)</div>}
                {typedLines >= 3 && <div className="m-term-out text-emerald-400">✔ Real-time telemetry receiver online (2ms flush)</div>}
                {typedLines >= 4 && <div className="m-term-out text-white font-medium">Listening for assistant turns, tool exceptions, and user signals</div>}
                {typedLines >= 5 && <div className="m-term-out text-zinc-500">Live dashboard ready at http://localhost:5173</div>}
              </div>
            )}
          </div>
        </div>

        {/* Right: Gently Moving Node Graph Visualization */}
        <div className="m-setup-graph-card">
          <div className="m-graph-header">
            <span className="m-graph-tag">
              <Network size={13} />
              <span>LIVE TELEMETRY TOPOLOGY</span>
            </span>
            <span className="status status-healthy"><span />Active</span>
          </div>

          <div className="m-graph-body">
            <svg className="m-graph-svg" viewBox="0 0 320 180" fill="none">
              {/* Animated Connecting Pulse Line */}
              <path
                d="M 50 90 C 110 30, 150 150, 210 90 L 270 90"
                stroke="rgba(168, 85, 247, 0.4)"
                strokeWidth="2"
                strokeDasharray="4 4"
                className="m-graph-dash-path"
              />
              <path
                d="M 50 90 C 110 30, 150 150, 210 90 L 270 90"
                stroke="url(#graph-gradient)"
                strokeWidth="2.5"
                className="m-graph-flow-path"
              />

              <defs>
                <linearGradient id="graph-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#38bdf8" />
                  <stop offset="50%" stopColor="#a855f7" />
                  <stop offset="100%" stopColor="#34d399" />
                </linearGradient>
              </defs>

              {/* Node 1: Agent Runtime */}
              <g className="m-graph-node node-agent" transform="translate(50, 90)">
                <circle r="18" fill="#090a0f" stroke="#38bdf8" strokeWidth="2" />
                <circle r="26" fill="none" stroke="rgba(56, 189, 248, 0.25)" className="m-pulse-ring" />
                <text textAnchor="middle" dy="4" fill="#ffffff" fontSize="9" fontFamily="var(--font-mono)">AGENT</text>
              </g>

              {/* Node 2: Tervik Deterministic Ingestion */}
              <g className="m-graph-node node-tervik" transform="translate(160, 90)">
                <circle r="22" fill="#090a0f" stroke="#a855f7" strokeWidth="2" />
                <circle r="32" fill="none" stroke="rgba(168, 85, 247, 0.3)" className="m-pulse-ring delay-1" />
                <text textAnchor="middle" dy="-2" fill="#ffffff" fontSize="9" fontWeight="500" fontFamily="var(--font-mono)">TERVIK</text>
                <text textAnchor="middle" dy="9" fill="#a855f7" fontSize="7" fontFamily="var(--font-mono)">2ms</text>
              </g>

              {/* Node 3: Synthesis & Replay */}
              <g className="m-graph-node node-eval" transform="translate(270, 90)">
                <circle r="18" fill="#090a0f" stroke="#34d399" strokeWidth="2" />
                <circle r="26" fill="none" stroke="rgba(52, 211, 153, 0.25)" className="m-pulse-ring delay-2" />
                <text textAnchor="middle" dy="4" fill="#ffffff" fontSize="9" fontFamily="var(--font-mono)">EVAL</text>
              </g>
            </svg>

            <div className="m-graph-footer">
              <span>Non-blocking async telemetry</span>
              <span>100% deterministic rules</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
