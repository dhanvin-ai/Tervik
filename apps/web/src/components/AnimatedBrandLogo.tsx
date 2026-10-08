import { useEffect, useState } from 'react';

export function AnimatedBrandLogo() {
  const [isRendered, setIsRendered] = useState(false);

  useEffect(() => {
    setIsRendered(true);
  }, []);

  return (
    <div className={`m-brand-animated ${isRendered ? 'is-animated' : ''}`}>
      {/* Light Rays Burst Effect */}
      <div className="m-logo-rays" aria-hidden="true" />

      {/* SVG Outline Drawing and Solid Fill Box */}
      <div className="m-logo-icon-box">
        <svg viewBox="0 0 24 24" className="m-logo-svg" fill="none">
          {/* Tile Outline Rectangle with draw-in stroke */}
          <rect
            x="2"
            y="2"
            width="20"
            height="20"
            rx="5"
            className="m-logo-rect"
          />
          {/* T-Shape / Bars with draw-in and fill */}
          <path
            d="M 7 7 L 17 7 M 12 7 L 12 17"
            strokeWidth="3.2"
            strokeLinecap="round"
            className="m-logo-letter"
          />
        </svg>
      </div>

      <span className="m-brand-text">
        tervik<span className="logo-dot">.</span>
      </span>
    </div>
  );
}
