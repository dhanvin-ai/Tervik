import { useScrollReveal } from '../hooks/useMotion';
import { Star } from 'lucide-react';

export function SocialProofMotion() {
  const { ref, isRevealed } = useScrollReveal(0.15);

  const TESTIMONIALS = [
    {
      quote: 'Tervik gave our coding agent the visibility it was missing. Within 10 minutes we found two repeated tool error loops that were silently frustrating users.',
      author: 'Autonomous Agent Infrastructure Team',
      role: 'Production agent deployment · 100k+ monthly runs',
      badge: 'DEV TOOLS',
    },
    {
      quote: 'Deterministic triage rules replaced flaky LLM-as-a-judge evaluators. Our triage latency dropped from 45 seconds to 2 milliseconds.',
      author: 'Senior Staff Engineer, AI Platform',
      role: 'Enterprise workflow agent · 500k turns/wk',
      badge: 'FINTECH',
    },
    {
      quote: 'The ability to turn real user corrections into replay evaluation datasets gave us the confidence to ship prompt updates daily instead of weekly.',
      author: 'Lead Agent Architect',
      role: 'Multi-agent developer assistant',
      badge: 'DEVELOPER AI',
    },
    {
      quote: 'Zero telemetry drops and completely local-first. We can test proprietary models without exposing customer prompts to any third party.',
      author: 'Security & Compliance Lead',
      role: 'Healthcare Agentic Workflows',
      badge: 'HEALTHCARE',
    },
  ];

  return (
    <div ref={ref} className={`m-social-proof-system ${isRevealed ? 'is-revealed' : ''}`}>
      {/* 1. Growing Benchmark Bars & Traveling Dots Row */}
      <div className="m-benchmarks-grid">
        {/* Metric 1 */}
        <div className="m-benchmark-card">
          <div className="m-benchmark-travel-track">
            <span className="m-traveling-dot" />
          </div>
          <div className="m-benchmark-top">
            <strong className="m-stat-number">100%</strong>
            <span className="m-stat-tag">GROUNDED</span>
          </div>
          <span className="m-stat-label">Evidence-Backed Triage</span>
          <p>Every cluster cites real messages and tool payloads. Zero ungrounded summaries.</p>
          <div className="m-benchmark-bar-track">
            <div className="m-benchmark-bar-fill fill-100" />
          </div>
        </div>

        {/* Metric 2 */}
        <div className="m-benchmark-card">
          <div className="m-benchmark-travel-track">
            <span className="m-traveling-dot delay-1" />
          </div>
          <div className="m-benchmark-top">
            <strong className="m-stat-number">98%</strong>
            <span className="m-stat-tag text-emerald-400">FASTER</span>
          </div>
          <span className="m-stat-label">Faster Diagnosis</span>
          <p>Zero manual log scouring across distributed agent workers and nested spans.</p>
          <div className="m-benchmark-bar-track">
            <div className="m-benchmark-bar-fill fill-98" />
          </div>
        </div>

        {/* Metric 3 */}
        <div className="m-benchmark-card">
          <div className="m-benchmark-travel-track">
            <span className="m-traveling-dot delay-2" />
          </div>
          <div className="m-benchmark-top">
            <strong className="m-stat-number">40%</strong>
            <span className="m-stat-tag text-amber-400">REDUCED</span>
          </div>
          <span className="m-stat-label">Fewer Repeated Errors</span>
          <p>Catch recurring failure loops and prompt regressions before they affect users.</p>
          <div className="m-benchmark-bar-track">
            <div className="m-benchmark-bar-fill fill-40" />
          </div>
        </div>
      </div>

      {/* 2. Slow Testimonial Marquee (Pauses on Hover / Focus) */}
      <div className="m-marquee-section">
        <div className="m-marquee-wrapper" tabIndex={0} aria-label="Testimonials marquee">
          <div className="m-marquee-track">
            {/* First Set */}
            {TESTIMONIALS.map((t, idx) => (
              <div key={idx} className="m-marquee-card">
                <div className="m-marquee-card-header">
                  <div className="m-quote-stars">
                    {[...Array(5)].map((_, i) => (
                      <Star key={i} size={11} fill="#eab308" color="#eab308" />
                    ))}
                  </div>
                  <span className="m-marquee-badge">{t.badge}</span>
                </div>
                <p className="m-marquee-quote">&quot;{t.quote}&quot;</p>
                <div className="m-marquee-author">
                  <span className="user-avatar">{t.author.slice(0, 1)}</span>
                  <div>
                    <strong>{t.author}</strong>
                    <small>{t.role}</small>
                  </div>
                </div>
              </div>
            ))}

            {/* Duplicated Set for Seamless Infinite Loop */}
            {TESTIMONIALS.map((t, idx) => (
              <div key={`dup-${idx}`} className="m-marquee-card" aria-hidden="true">
                <div className="m-marquee-card-header">
                  <div className="m-quote-stars">
                    {[...Array(5)].map((_, i) => (
                      <Star key={i} size={11} fill="#eab308" color="#eab308" />
                    ))}
                  </div>
                  <span className="m-marquee-badge">{t.badge}</span>
                </div>
                <p className="m-marquee-quote">&quot;{t.quote}&quot;</p>
                <div className="m-marquee-author">
                  <span className="user-avatar">{t.author.slice(0, 1)}</span>
                  <div>
                    <strong>{t.author}</strong>
                    <small>{t.role}</small>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
