import { useState, useEffect } from 'react';
import { ShieldCheck, MessageSquare, Layers3, GitBranch, Check, ArrowRight } from 'lucide-react';
import { useScrollReveal, usePrefersReducedMotion } from '../hooks/useMotion';

interface LayerInfo {
  id: number;
  number: string;
  name: string;
  subtitle: string;
  metric: string;
  icon: typeof MessageSquare;
  color: string;
  details: string[];
}

const LAYERS: LayerInfo[] = [
  {
    id: 4,
    number: 'LAYER 4',
    name: 'Evaluation & Replay',
    subtitle: 'Verify fixes before production deployment',
    metric: '99.4% Pass Rate',
    icon: ShieldCheck,
    color: '#34d399',
    details: ['Regression prevention', 'Reproducibility scoring', 'Candidate vs baseline diff'],
  },
  {
    id: 3,
    number: 'LAYER 3',
    name: 'Cluster Synthesis',
    subtitle: 'Group recurring patterns across sessions',
    metric: '5 Clusters Synthesized',
    icon: Layers3,
    color: '#a855f7',
    details: ['Evidence cited for every issue', 'Prioritized by severity', '1-click dataset export'],
  },
  {
    id: 2,
    number: 'LAYER 2',
    name: 'Signal & Failure Detection',
    subtitle: 'Deterministic triage on every turn',
    metric: '30 Intercepts Flagged',
    icon: GitBranch,
    color: '#f59e0b',
    details: ['Transparent regex rules', 'No flaky judge models', 'Real-time turn triage'],
  },
  {
    id: 1,
    number: 'LAYER 1',
    name: 'Traces & Telemetry',
    subtitle: 'The raw non-blocking record of an agent run',
    metric: 'Sub-2ms Ingestion',
    icon: MessageSquare,
    color: '#38bdf8',
    details: ['Async background flush', 'Zero telemetry drops', 'Complete tool payloads'],
  },
];

export function IsometricArchitecture() {
  const { ref, isRevealed } = useScrollReveal(0.2);
  const prefersReduced = usePrefersReducedMotion();
  const [activeLayer, setActiveLayer] = useState<number>(3);
  const [isExploded, setIsExploded] = useState(false);

  useEffect(() => {
    if (isRevealed || prefersReduced) {
      const timer = setTimeout(() => setIsExploded(true), 350);
      return () => clearTimeout(timer);
    }
  }, [isRevealed, prefersReduced]);

  return (
    <div ref={ref} className={`m-iso-system ${isRevealed ? 'is-in-view' : ''} ${isExploded ? 'is-exploded' : ''}`}>
      {/* Visual Controls / Status Header */}
      <div className="m-iso-top-bar">
        <div className="m-iso-status">
          <span className="pulse-dot" />
          <span>FOUR DETERMINISTIC LAYERS</span>
          <span className="m-badge-divider">/</span>
          <span className="text-zinc-400">ISOMETRIC ARCHITECTURE</span>
        </div>
        <button
          className="m-iso-toggle-btn"
          onClick={() => setIsExploded(!isExploded)}
          aria-label={isExploded ? 'Collapse isometric layers' : 'Explode isometric layers'}
        >
          <span>{isExploded ? 'Collapsed View' : 'Exploded View'}</span>
          <ArrowRight size={13} className={isExploded ? 'rotate-90' : ''} />
        </button>
      </div>

      <div className="m-iso-viewport">
        {/* Left: 3D Isometric Exploding Layers Stage */}
        <div className="m-iso-stage-wrapper">
          <div className="m-iso-stage">
            {/* Ambient Base Shadow & Floor Grid */}
            <div className="m-iso-floor-grid" />

            {/* Connecting Vertical Energy Beam */}
            <div className="m-iso-beam-axis">
              <span className="m-iso-traveling-pulse" />
            </div>

            {/* The 4 Floating Isometric Layers (rendered top-to-bottom for 3D stacking) */}
            {LAYERS.map(layer => {
              const Icon = layer.icon;
              const isActive = activeLayer === layer.id;
              // Elevation offsets when exploded
              const elevationPx = isExploded ? (layer.id - 1) * 72 : 0;

              return (
                <div
                  key={layer.id}
                  className={`m-iso-layer-slab layer-${layer.id} ${isActive ? 'active-slab' : ''}`}
                  style={{
                    transform: `translate3d(0, ${-elevationPx}px, ${elevationPx * 0.8}px)`,
                    zIndex: layer.id * 10,
                  }}
                  onClick={() => setActiveLayer(layer.id)}
                  onMouseEnter={() => setActiveLayer(layer.id)}
                >
                  {/* Layer Surface Glass Plate */}
                  <div className="m-iso-plate-surface">
                    <div className="m-iso-plate-header">
                      <div className="m-iso-plate-badge" style={{ color: layer.color }}>
                        <Icon size={14} />
                        <span>{layer.number}</span>
                      </div>
                      <span className="m-iso-plate-metric">{layer.metric}</span>
                    </div>

                    <div className="m-iso-plate-title">{layer.name}</div>

                    {/* Circuit Track Lines on Glass */}
                    <div className="m-iso-plate-tracks">
                      <span className="m-iso-track" />
                      <span className="m-iso-track track-right" />
                      <span className="m-iso-node-dot" style={{ borderColor: layer.color }} />
                    </div>
                  </div>

                  {/* 3D Depth Edges */}
                  <div className="m-iso-plate-edge-left" />
                  <div className="m-iso-plate-edge-right" />
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Active Layer Inspector & Callout Details */}
        <div className="m-iso-inspector">
          {LAYERS.map(layer => {
            const Icon = layer.icon;
            const isCurrent = activeLayer === layer.id;
            return (
              <div
                key={layer.id}
                className={`m-iso-card ${isCurrent ? 'active' : ''}`}
                onClick={() => setActiveLayer(layer.id)}
              >
                <div className="m-iso-card-header">
                  <div className="m-iso-card-icon" style={{ color: layer.color, borderColor: `${layer.color}40` }}>
                    <Icon size={18} />
                  </div>
                  <div>
                    <span className="m-iso-card-number">{layer.number}</span>
                    <h3 className="m-iso-card-title">{layer.name}</h3>
                  </div>
                  <span className="m-iso-card-pill">{layer.metric}</span>
                </div>

                <p className="m-iso-card-sub">{layer.subtitle}</p>

                {isCurrent && (
                  <div className="m-iso-card-details">
                    {layer.details.map((detail, i) => (
                      <div key={i} className="m-iso-detail-item">
                        <Check size={13} style={{ color: layer.color }} />
                        <span>{detail}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
