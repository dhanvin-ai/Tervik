import type { CSSProperties } from 'react';
import { BRAND_LOGOS, type LogoMark } from './brandLogos';

// Optical heights in px. Wordmarks differ in cap height and descenders, so each is tuned by eye.
const SIZES: Record<string, { icon: number; wordmark: number }> = {
  'Claude Code': { icon: 17, wordmark: 30 },
  Cursor: { icon: 24, wordmark: 16 },
  OpenCode: { icon: 20, wordmark: 22 },
  Codex: { icon: 24, wordmark: 18 },
  Devin: { icon: 22, wordmark: 18 },
  Antigravity: { icon: 22, wordmark: 23 },
  LangChain: { icon: 23, wordmark: 22 },
};

// Each half of the track repeats the set so the loop stays seamless on very wide screens.
const COPIES_PER_HALF = 2;

function Mark({ mark, height, className }: { mark: LogoMark; height: number; className: string }) {
  return (
    <svg className={className} viewBox={mark.viewBox} fill="currentColor" fillRule={mark.fillRule}
      style={{ '--h': `${height}px` } as CSSProperties} aria-hidden="true" focusable="false">
      {mark.paths.map((path, index) => <path key={index} {...path} />)}
    </svg>
  );
}

function LogoList({ hidden = false }: { hidden?: boolean }) {
  const items = Array.from({ length: COPIES_PER_HALF }, (_, copy) => BRAND_LOGOS.map(logo => ({ logo, copy }))).flat();
  return (
    <ul className="m-works-list" aria-hidden={hidden || undefined}>
      {items.map(({ logo, copy }) => (
        <li key={`${logo.name}-${copy}`} className={copy ? 'm-works-logo is-repeat' : 'm-works-logo'}
          aria-hidden={copy ? true : undefined} title={logo.name}>
          <Mark mark={logo.icon} height={SIZES[logo.name].icon} className="m-works-icon" />
          <Mark mark={logo.wordmark} height={SIZES[logo.name].wordmark} className="m-works-wordmark" />
          {!hidden && !copy && <span className="m-works-name">{logo.name}</span>}
        </li>
      ))}
    </ul>
  );
}

export function WorksWithMarquee() {
  return (
    <section className="m-works-with" aria-labelledby="m-works-caption">
      <p id="m-works-caption" className="m-works-caption">Works with the coding agents and frameworks you already use</p>
      <div className="m-works-marquee">
        <div className="m-works-track">
          <LogoList />
          <LogoList hidden />
        </div>
      </div>
    </section>
  );
}
