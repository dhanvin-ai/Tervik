import { useEffect, useRef, type RefObject } from 'react';

// 4x4 Bayer matrix, normalized to 0..1 thresholds.
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map(value => (value + 0.5) / 16);
const FRAME_MS = 1000 / 24;

export type DitherTone = 'gray' | 'blue';
const TONES: Record<DitherTone, [number, number, number]> = {
  gray: [150, 150, 150],
  blue: [84, 112, 245],
};

export interface DitherOptions {
  tone?: DitherTone;
  /** CSS pixels per dither pixel. */
  cell?: number;
  /** 0 = uniform texture; 1 = dark center that brightens toward the edges. */
  vignette?: number;
  /** Overall brightness multiplier. */
  intensity?: number;
  /** Noise scale; smaller values give larger swirls. */
  scale?: number;
  speed?: number;
  seed?: number;
}

/** Smooth flowing field in 0..1, built from warped sines so it stays cheap per pixel. */
function field(x: number, y: number, t: number, seed: number) {
  const warp = Math.sin(y * 0.9 + t * 0.35 + seed) * 1.6 + Math.sin(x * 0.4 - t * 0.2 + seed * 2.1);
  const a = Math.sin(x * 1.1 + warp + t * 0.25);
  const b = Math.cos(y * 1.3 - warp * 0.7 - t * 0.3 + seed);
  const c = Math.sin((x + y) * 0.6 + t * 0.15 + seed * 0.5);
  return 0.5 + 0.5 * (a * 0.45 + b * 0.35 + c * 0.2);
}

/** Paints one dither frame into an ImageData buffer. Shared by the canvas and the text renderer. */
export function paintDither(image: ImageData, t: number, options: Required<Omit<DitherOptions, 'cell'>>, mask?: Uint8ClampedArray) {
  const { width, height, data } = image;
  const [r, g, b] = TONES[options.tone];
  const scale = options.scale / Math.max(width, height) * 40;
  for (let y = 0; y < height; y++) {
    const ny = (y / height) * 2 - 1;
    for (let x = 0; x < width; x++) {
      const index = (y * width + x) * 4;
      const coverage = mask ? mask[index + 3] / 255 : 1;
      if (coverage < 0.35) { data[index + 3] = 0; continue; }
      const nx = (x / width) * 2 - 1;
      let value = field(x * scale, y * scale, t * options.speed, options.seed);
      if (options.vignette > 0) {
        const edge = Math.min(1, Math.max(0, (Math.max(Math.abs(nx), Math.abs(ny) * 0.9) - 0.25) / 0.75));
        value *= 1 - options.vignette + options.vignette * edge * edge * (3 - 2 * edge);
      }
      value *= options.intensity;
      const on = value > BAYER[(y & 3) * 4 + (x & 3)];
      if (mask) {
        // Glyph pixels: bright where the field is lit, dim where it is dark, never fully empty.
        const level = on ? 255 : 58;
        data[index] = level; data[index + 1] = level; data[index + 2] = level; data[index + 3] = 255;
      } else if (on) {
        data[index] = r; data[index + 1] = g; data[index + 2] = b;
        data[index + 3] = Math.min(255, 36 + value * value * 190);
      } else {
        data[index + 3] = 0;
      }
    }
  }
}

export function withDefaults(options: DitherOptions): Required<Omit<DitherOptions, 'cell'>> & { cell: number } {
  return { tone: 'gray', cell: 2, vignette: 0.6, intensity: 0.9, scale: 1, speed: 1, seed: 0, ...options };
}

/**
 * Runs a paint loop on a canvas sized to its parent: 24 fps while visible,
 * paused offscreen or in background tabs, one static frame for reduced motion.
 */
export function useDitherLoop(
  canvasRef: RefObject<HTMLCanvasElement | null>,
  cell: number,
  draw: (ctx: CanvasRenderingContext2D, width: number, height: number, t: number) => void,
  deps: unknown[] = [],
) {
  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !parent || !ctx) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame: number | null = null;
    let last = 0;
    let visible = false;
    const start = performance.now() - Math.random() * 20000;

    const resize = () => {
      const width = Math.max(1, Math.ceil(parent.clientWidth / cell));
      const height = Math.max(1, Math.ceil(parent.clientHeight / cell));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      draw(ctx, width, height, (performance.now() - start) / 1000);
    };
    const tick = (now: number) => {
      frame = null;
      if (!visible || reduced.matches || document.hidden) return;
      if (now - last >= FRAME_MS) {
        last = now;
        draw(ctx, canvas.width, canvas.height, (now - start) / 1000);
      }
      frame = requestAnimationFrame(tick);
    };
    const play = () => { if (frame === null && visible && !reduced.matches && !document.hidden) frame = requestAnimationFrame(tick); };

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(parent);
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      play();
    }, { rootMargin: '120px' });
    intersection.observe(canvas);
    document.addEventListener('visibilitychange', play);
    reduced.addEventListener('change', play);
    resize();
    return () => {
      if (frame !== null) cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      intersection.disconnect();
      document.removeEventListener('visibilitychange', play);
      reduced.removeEventListener('change', play);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cell, ...deps]);
}

/** Animated dither texture that fills its positioned parent. Decorative only. */
export function DitherCanvas({ className = '', ...options }: DitherOptions & { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const settings = withDefaults(options);
  const imageRef = useRef<ImageData | null>(null);
  useDitherLoop(canvasRef, settings.cell, (ctx, width, height, t) => {
    if (!imageRef.current || imageRef.current.width !== width || imageRef.current.height !== height) {
      imageRef.current = ctx.createImageData(width, height);
    }
    paintDither(imageRef.current, t, settings);
    ctx.putImageData(imageRef.current, 0, 0);
  }, [settings.tone, settings.vignette, settings.intensity, settings.scale, settings.speed, settings.seed]);
  return <canvas ref={canvasRef} className={`lp-dither ${className}`} aria-hidden="true" />;
}
