import { useEffect, useRef, useState } from 'react';
import { paintDither, useDitherLoop, withDefaults } from './DitherCanvas';

const CELL = 2;
const FONT_FAMILY = '"Geist Sans", "Geist", sans-serif';
const WEIGHT = 700;
const LINE_HEIGHT = 1.12;
// Below this size a single line gets too small to read as dithered pixels, so it wraps.
const MIN_SINGLE_LINE = 56;

type Layout = { size: number; lines: string[] };

/** Splits at the space that keeps the two lines closest in width. */
function balancedSplit(text: string, measure: CanvasRenderingContext2D) {
  const words = text.split(' ');
  let best: string[] = [text];
  let bestWidth = Infinity;
  for (let i = 1; i < words.length; i++) {
    const lines = [words.slice(0, i).join(' '), words.slice(i).join(' ')];
    const widest = Math.max(...lines.map(line => measure.measureText(line).width));
    if (widest < bestWidth) { bestWidth = widest; best = lines; }
  }
  return best;
}

/** Headline drawn as animated dithered pixels, sized to fill its container. */
export function DitherText({ text, maxSize = 132, className = '' }: { text: string; maxSize?: number; className?: string }) {
  const boxRef = useRef<HTMLSpanElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [layout, setLayout] = useState<Layout>({ size: 0, lines: [text] });
  const cache = useRef<{ key: string; mask: Uint8ClampedArray; image: ImageData } | null>(null);
  const settings = withDefaults({ vignette: 0, intensity: 1.15, scale: 1.4, speed: 0.8 });

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const measure = document.createElement('canvas').getContext('2d');
    if (!measure) return;
    let cancelled = false;
    const fit = () => {
      measure.font = `${WEIGHT} 100px ${FONT_FAMILY}`;
      const sizeFor = (lines: string[]) => {
        const widest = Math.max(...lines.map(line => measure.measureText(line).width), 1);
        return Math.min(maxSize, Math.floor((100 * box.clientWidth / widest) * 0.98));
      };
      let lines = [text];
      let size = sizeFor(lines);
      if (size < MIN_SINGLE_LINE && text.includes(' ')) {
        lines = balancedSplit(text, measure);
        size = sizeFor(lines);
      }
      if (!cancelled) setLayout({ size: Math.max(20, size), lines });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(box);
    document.fonts?.load(`${WEIGHT} 100px ${FONT_FAMILY}`).then(() => { cache.current = null; fit(); }).catch(() => undefined);
    return () => { cancelled = true; observer.disconnect(); };
  }, [text, maxSize]);

  useDitherLoop(canvasRef, CELL, (ctx, width, height, t) => {
    const { size, lines } = layout;
    if (!size) return;
    const key = `${width}x${height}:${size}:${lines.join('|')}`;
    if (cache.current?.key !== key) {
      const offscreen = document.createElement('canvas');
      offscreen.width = width;
      offscreen.height = height;
      const draw = offscreen.getContext('2d');
      if (!draw) return;
      const lineHeight = (size * LINE_HEIGHT) / CELL;
      draw.font = `${WEIGHT} ${size / CELL}px ${FONT_FAMILY}`;
      draw.textAlign = 'center';
      draw.textBaseline = 'middle';
      draw.fillStyle = '#fff';
      const top = height / 2 - (lineHeight * (lines.length - 1)) / 2;
      lines.forEach((line, index) => draw.fillText(line, width / 2, top + index * lineHeight + size / CELL * 0.04));
      cache.current = { key, mask: draw.getImageData(0, 0, width, height).data, image: ctx.createImageData(width, height) };
    }
    paintDither(cache.current.image, t, settings, cache.current.mask);
    ctx.putImageData(cache.current.image, 0, 0);
  }, [layout]);

  const height = layout.size ? Math.ceil(layout.size * (LINE_HEIGHT * layout.lines.length + 0.1)) : undefined;
  return (
    // Spans keep this valid inside a heading element.
    <span className={`lp-dither-text ${className}`}>
      <span className="lp-sr">{text}</span>
      <span ref={boxRef} className="lp-dither-text-box" style={{ height }}>
        <canvas ref={canvasRef} className="lp-dither" aria-hidden="true" />
      </span>
    </span>
  );
}
