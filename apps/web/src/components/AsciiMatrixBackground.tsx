import { useEffect, useRef, type CSSProperties } from 'react';

const CHAR_SET = ['>', '#', '$', '%', '*', '&', '{', '}', '\\', '|', '@', '/', '+', '-', '=', '(', ')', ':', ';', '0', '8', 'B', 'S', 'X', '~', '<'];
const SPOTLIGHT_RADIUS = 100;
// The always-on grid stays this far from the hero text, then fades in over FEATHER.
const TEXT_CLEARANCE = 40;
const FEATHER = 140;
const AMBIENT_ALPHA = .26;

/**
 * The hero's symbol grid, on two canvases that share one set of symbols:
 * - the ambient layer covers the whole box in dim white and keeps changing,
 *   fading out around the hero text so it never sits behind it;
 * - the spotlight layer shows the same symbols in bright white under the pointer.
 */
export function AsciiMatrixBackground() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const ambientRef = useRef<HTMLCanvasElement | null>(null);
  const spotlightRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const ambientCanvas = ambientRef.current;
    const spotlightCanvas = spotlightRef.current;
    const hero = container?.closest<HTMLElement>('.m-hero');
    const content = hero?.querySelector<HTMLElement>('.m-hero-content');
    const ambient = ambientCanvas?.getContext('2d');
    const spotlight = spotlightCanvas?.getContext('2d');
    if (!container || !ambientCanvas || !spotlightCanvas || !hero || !ambient || !spotlight) return;

    let frame: number | null = null;
    let loop: number | null = null;
    let disposed = false;
    let revealed = false;
    let inView = true;
    let pointerX = 0;
    let pointerY = 0;
    let cols = 0;
    let rows = 0;
    let symbols: string[] = [];
    let alpha = new Float32Array(0);      // ambient brightness per cell; 0 near the text
    let ambientCells: number[] = [];      // cells the ambient layer shows
    let lastTick = 0;
    const cellWidth = 12;
    const cellHeight = 16;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    const paintCell = (index: number) => {
      const x = (index % cols) * cellWidth;
      const y = Math.floor(index / cols) * cellHeight;
      const cx = x + cellWidth / 2;
      const cy = y + cellHeight / 2;
      spotlight.clearRect(x, y, cellWidth, cellHeight);
      spotlight.fillText(symbols[index], cx, cy);
      ambient.clearRect(x, y, cellWidth, cellHeight);
      if (alpha[index] > 0) {
        ambient.globalAlpha = alpha[index];
        ambient.fillText(symbols[index], cx, cy);
      }
    };

    /** The boxes the hero's words and buttons occupy, in the grid's coordinates:
     * each line of text, and each button or link. */
    const textBoxes = () => {
      if (!content) return [];
      const origin = container.getBoundingClientRect();
      const boxes: [number, number, number, number][] = [];
      const add = (rect: DOMRect) => {
        if (rect.width && rect.height) boxes.push([rect.left - origin.left, rect.top - origin.top, rect.right - origin.left, rect.bottom - origin.top]);
      };
      const range = document.createRange();
      const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent?.trim()) continue;
        range.selectNodeContents(node);
        for (const rect of range.getClientRects()) add(rect);
      }
      content.querySelectorAll('a, button').forEach(element => add(element.getBoundingClientRect()));
      return boxes;
    };

    /** How bright each cell of the ambient layer is: nothing within TEXT_CLEARANCE
     * of the words and buttons, then a smooth fade up to full over FEATHER pixels. */
    const measureClearance = () => {
      alpha = new Float32Array(cols * rows);
      ambientCells = [];
      const boxes = textBoxes();
      for (let index = 0; index < cols * rows; index++) {
        const cx = (index % cols) * cellWidth + cellWidth / 2;
        const cy = Math.floor(index / cols) * cellHeight + cellHeight / 2;
        let distance = Infinity;
        for (const [left, top, right, bottom] of boxes) {
          const dx = Math.max(left - cx, 0, cx - right);
          const dy = Math.max(top - cy, 0, cy - bottom);
          distance = Math.min(distance, Math.hypot(dx, dy));
        }
        const t = Math.min(1, Math.max(0, distance - TEXT_CLEARANCE) / FEATHER);
        if (t <= 0) continue;
        // Uneven brightness gives the field some texture.
        alpha[index] = AMBIENT_ALPHA * t * t * (3 - 2 * t) * (.55 + Math.random() * .45);
        ambientCells.push(index);
      }
    };

    const drawGrid = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      for (const [canvas, ctx] of [[ambientCanvas, ambient], [spotlightCanvas, spotlight]] as const) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.font = '500 13px "Geist Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#fff';
      }
      cols = Math.ceil(width / cellWidth);
      rows = Math.ceil(height / cellHeight);
      symbols = Array.from({ length: cols * rows },
        () => CHAR_SET[Math.floor(Math.random() * CHAR_SET.length)]);
      measureClearance();
      symbols.forEach((_, index) => paintCell(index));
    };

    // The words rise into place as the page loads; measure again once they settle.
    let settle: number | null = null;
    const remeasure = (event: AnimationEvent) => {
      if (event.target === content) return;  // the hero's own scroll drift
      if (settle !== null) clearTimeout(settle);
      settle = window.setTimeout(() => {
        settle = null;
        measureClearance();
        symbols.forEach((_, index) => paintCell(index));
      }, 120);
    };

    const change = (index: number) => {
      const current = CHAR_SET.indexOf(symbols[index]);
      const offset = 1 + Math.floor(Math.random() * (CHAR_SET.length - 1));
      symbols[index] = CHAR_SET[(current + offset) % CHAR_SET.length];
      paintCell(index);
    };

    /** Cells inside the spotlight circle. */
    const spotlightCells = () => {
      const cells: number[] = [];
      const startCol = Math.max(0, Math.floor((pointerX - SPOTLIGHT_RADIUS) / cellWidth));
      const endCol = Math.min(cols - 1, Math.ceil((pointerX + SPOTLIGHT_RADIUS) / cellWidth));
      const startRow = Math.max(0, Math.floor((pointerY - SPOTLIGHT_RADIUS) / cellHeight));
      const endRow = Math.min(rows - 1, Math.ceil((pointerY + SPOTLIGHT_RADIUS) / cellHeight));
      for (let row = startRow; row <= endRow; row++) {
        for (let col = startCol; col <= endCol; col++) {
          const x = col * cellWidth + cellWidth / 2;
          const y = row * cellHeight + cellHeight / 2;
          if (Math.hypot(x - pointerX, y - pointerY) <= SPOTLIGHT_RADIUS + cellHeight / 2) cells.push(row * cols + col);
        }
      }
      return cells;
    };

    const canAnimate = () => inView && !reducedMotion.matches && !document.hidden;

    const tick = (now: number) => {
      if (!canAnimate()) { loop = null; return; }
      if (now - lastTick >= 75) {
        lastTick = now;
        // The ambient field changes a few symbols at a time, everywhere.
        for (let i = Math.ceil(ambientCells.length * .02); i > 0; i--) {
          change(ambientCells[Math.floor(Math.random() * ambientCells.length)]);
        }
        // Under the pointer, a quarter of the symbols change on every tick.
        if (revealed) {
          const cells = spotlightCells();
          for (let i = 0; i < Math.ceil(cells.length * .25); i++) {
            const pick = i + Math.floor(Math.random() * (cells.length - i));
            [cells[i], cells[pick]] = [cells[pick], cells[i]];
            change(cells[i]);
          }
        }
      }
      loop = requestAnimationFrame(tick);
    };

    const start = () => {
      if (loop === null && canAnimate()) {
        lastTick = performance.now();
        loop = requestAnimationFrame(tick);
      }
    };
    const stop = () => {
      if (loop !== null) cancelAnimationFrame(loop);
      loop = null;
    };

    const hide = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      revealed = false;
      spotlightCanvas.style.opacity = '0';
    };

    const reveal = (event: PointerEvent) => {
      if (event.pointerType === 'touch') { hide(); return; }
      const rect = container.getBoundingClientRect();
      pointerX = event.clientX - rect.left;
      pointerY = event.clientY - rect.top;
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        container.style.setProperty('--spotlight-x', `${pointerX}px`);
        container.style.setProperty('--spotlight-y', `${pointerY}px`);
        spotlightCanvas.style.opacity = '1';
        revealed = true;
        start();
        frame = null;
      });
    };

    const handleVisibility = () => { if (document.hidden) { hide(); stop(); } else start(); };
    const handleMotionPreference = () => { if (reducedMotion.matches) stop(); else start(); };
    const visibilityObserver = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      if (inView) start(); else { hide(); stop(); }
    });
    visibilityObserver.observe(hero);
    // Redraw when the box or the text block changes size.
    const resizeObserver = new ResizeObserver(() => { drawGrid(); hide(); });
    resizeObserver.observe(container);
    if (content) resizeObserver.observe(content);
    drawGrid();
    container.classList.add('is-ready');
    start();
    // Font loading can complete after the first draw.
    void document.fonts.ready.then(() => { if (!disposed) drawGrid(); });
    content?.addEventListener('animationend', remeasure);
    hero.addEventListener('pointermove', reveal, { passive: true });
    hero.addEventListener('pointerleave', hide);
    hero.addEventListener('pointercancel', hide);
    window.addEventListener('scroll', hide, { passive: true });
    window.addEventListener('blur', hide);
    document.addEventListener('visibilitychange', handleVisibility);
    reducedMotion.addEventListener('change', handleMotionPreference);

    return () => {
      disposed = true;
      hide();
      stop();
      if (settle !== null) clearTimeout(settle);
      content?.removeEventListener('animationend', remeasure);
      resizeObserver.disconnect();
      visibilityObserver.disconnect();
      hero.removeEventListener('pointermove', reveal);
      hero.removeEventListener('pointerleave', hide);
      hero.removeEventListener('pointercancel', hide);
      window.removeEventListener('scroll', hide);
      window.removeEventListener('blur', hide);
      document.removeEventListener('visibilitychange', handleVisibility);
      reducedMotion.removeEventListener('change', handleMotionPreference);
    };
  }, []);

  return <div ref={containerRef} className="m-ascii-canvas-wrapper" aria-hidden="true"
    style={{ '--spotlight-radius': `${SPOTLIGHT_RADIUS}px` } as CSSProperties}>
    <canvas ref={ambientRef} className="m-ascii-canvas m-ascii-ambient" />
    <canvas ref={spotlightRef} className="m-ascii-canvas m-ascii-spotlight" />
  </div>;
}
