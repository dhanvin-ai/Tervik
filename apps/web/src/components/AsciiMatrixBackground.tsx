import { useEffect, useRef } from 'react';

const CHAR_SET = ['>', '#', '$', '%', '*', '&', '{', '}', '\\', '|', '@', '/', '+', '-', '=', '(', ')', ':', ';', '0', '8', 'B', 'S', 'X', '~', '<'];
const SPOTLIGHT_RADIUS = 70;
// The always-on grid covers the whole box. On and around the hero text it is
// nearly transparent (NEAR_ALPHA), then it brightens to AMBIENT_ALPHA over FEATHER pixels.
const NEAR_ALPHA = .06;
const FEATHER = 120;
const AMBIENT_ALPHA = .26;
// A changed symbol fades in over this long, so the field shimmers instead of flickering.
const FADE_MS = 420;
// How quickly the spotlight catches up with the pointer, and grows in or out (per 60 fps frame).
const FOLLOW = .2;
const PRESENCE = .14;

/**
 * The hero's symbol grid, on two canvases that share one set of symbols:
 * - the ambient layer covers the whole box in dim white and keeps changing,
 *   fading out around the hero text so it never sits behind it;
 * - the spotlight layer shows the same symbols in bright white under the pointer.
 *   It eases after the pointer, and grows in and out rather than switching.
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

    let loop: number | null = null;
    let disposed = false;
    let revealed = false;
    let inView = true;
    // Where the pointer is, and where the spotlight is drawn as it catches up.
    let targetX = 0;
    let targetY = 0;
    let spotX = 0;
    let spotY = 0;
    let presence = 0;                     // 0 hidden … 1 fully shown
    let cols = 0;
    let rows = 0;
    let symbols: string[] = [];
    let alpha = new Float32Array(0);      // ambient brightness per cell; 0 near the text
    let ambientCells: number[] = [];      // cells the ambient layer shows
    const fading = new Map<number, number>();  // cell → when its new symbol started fading in
    let lastTick = 0;
    let lastFrame = 0;
    const cellWidth = 12;
    const cellHeight = 16;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    /** Draws one cell on both layers, at `strength` (0–1) of its full brightness. */
    const paintCell = (index: number, strength = 1) => {
      const x = (index % cols) * cellWidth;
      const y = Math.floor(index / cols) * cellHeight;
      const cx = x + cellWidth / 2;
      const cy = y + cellHeight / 2;
      spotlight.clearRect(x, y, cellWidth, cellHeight);
      spotlight.globalAlpha = strength;
      spotlight.fillText(symbols[index], cx, cy);
      ambient.clearRect(x, y, cellWidth, cellHeight);
      if (alpha[index] > 0) {
        ambient.globalAlpha = alpha[index] * strength;
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

    /** How bright each cell of the ambient layer is: faint on and next to the words
     * and buttons, so they stay easy to read, then brightening over FEATHER pixels. */
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
        const t = Math.min(1, distance / FEATHER);
        const near = NEAR_ALPHA + (AMBIENT_ALPHA - NEAR_ALPHA) * t * t * (3 - 2 * t);
        // Uneven brightness gives the field some texture.
        alpha[index] = near * (.55 + Math.random() * .45);
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
      fading.clear();
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

    /** Gives a cell a new symbol, which then fades in. */
    const change = (index: number, now: number) => {
      const current = CHAR_SET.indexOf(symbols[index]);
      const offset = 1 + Math.floor(Math.random() * (CHAR_SET.length - 1));
      symbols[index] = CHAR_SET[(current + offset) % CHAR_SET.length];
      fading.set(index, now);
      paintCell(index, 0);
    };

    /** Cells inside the spotlight circle. */
    const spotlightCells = () => {
      const cells: number[] = [];
      const reach = SPOTLIGHT_RADIUS + cellHeight / 2;
      const startCol = Math.max(0, Math.floor((spotX - reach) / cellWidth));
      const endCol = Math.min(cols - 1, Math.ceil((spotX + reach) / cellWidth));
      const startRow = Math.max(0, Math.floor((spotY - reach) / cellHeight));
      const endRow = Math.min(rows - 1, Math.ceil((spotY + reach) / cellHeight));
      for (let row = startRow; row <= endRow; row++) {
        for (let col = startCol; col <= endCol; col++) {
          const x = col * cellWidth + cellWidth / 2;
          const y = row * cellHeight + cellHeight / 2;
          if (Math.hypot(x - spotX, y - spotY) <= reach) cells.push(row * cols + col);
        }
      }
      return cells;
    };

    /** Moves and sizes the spotlight's mask. It grows from 60% to full size as it appears. */
    const placeSpotlight = () => {
      container.style.setProperty('--spotlight-x', `${spotX}px`);
      container.style.setProperty('--spotlight-y', `${spotY}px`);
      container.style.setProperty('--spotlight-radius', `${SPOTLIGHT_RADIUS * (.6 + .4 * presence)}px`);
      spotlightCanvas.style.opacity = String(presence);
    };

    const canAnimate = () => inView && !reducedMotion.matches && !document.hidden;

    const tick = (now: number) => {
      if (!canAnimate()) { loop = null; return; }
      // Frame-rate independent easing toward the pointer and toward shown or hidden.
      const steps = Math.min(4, (now - (lastFrame || now)) / (1000 / 60));
      lastFrame = now;
      const ease = (rate: number) => 1 - Math.pow(1 - rate, steps);
      const goal = revealed ? 1 : 0;
      if (presence !== goal || spotX !== targetX || spotY !== targetY) {
        spotX += (targetX - spotX) * ease(FOLLOW);
        spotY += (targetY - spotY) * ease(FOLLOW);
        presence += (goal - presence) * ease(PRESENCE);
        if (Math.abs(targetX - spotX) < .1 && Math.abs(targetY - spotY) < .1) { spotX = targetX; spotY = targetY; }
        if (Math.abs(goal - presence) < .005) presence = goal;
        placeSpotlight();
      }

      if (now - lastTick >= 90) {
        lastTick = now;
        // The ambient field changes a few symbols at a time, everywhere.
        for (let i = Math.ceil(ambientCells.length * .012); i > 0; i--) {
          change(ambientCells[Math.floor(Math.random() * ambientCells.length)], now);
        }
        // Under the pointer, more of them change, so it reads as livelier.
        if (presence > .05) {
          const cells = spotlightCells();
          for (let i = Math.ceil(cells.length * .12); i > 0; i--) change(cells[Math.floor(Math.random() * cells.length)], now);
        }
      }

      // Fade in the symbols that changed recently.
      for (const [index, start] of fading) {
        const progress = Math.min(1, (now - start) / FADE_MS);
        paintCell(index, progress * (2 - progress));
        if (progress >= 1) fading.delete(index);
      }
      loop = requestAnimationFrame(tick);
    };

    const start = () => {
      if (loop === null && canAnimate()) {
        lastTick = performance.now();
        lastFrame = 0;
        loop = requestAnimationFrame(tick);
      }
    };
    const stop = () => {
      if (loop !== null) cancelAnimationFrame(loop);
      loop = null;
      // Finish any fades at once, so no symbol is left half drawn.
      for (const index of fading.keys()) paintCell(index);
      fading.clear();
    };

    /** Hides the spotlight: it shrinks and fades out, or vanishes at once without motion. */
    const hide = () => {
      revealed = false;
      if (!canAnimate()) { presence = 0; placeSpotlight(); }
    };

    const reveal = (event: PointerEvent) => {
      if (event.pointerType === 'touch') { hide(); return; }
      const rect = container.getBoundingClientRect();
      targetX = event.clientX - rect.left;
      targetY = event.clientY - rect.top;
      // Appearing: start where the pointer is rather than gliding in from the last spot.
      if (presence === 0) { spotX = targetX; spotY = targetY; }
      revealed = true;
      if (canAnimate()) start();
      else { spotX = targetX; spotY = targetY; presence = 1; placeSpotlight(); }
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
    placeSpotlight();
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

  return <div ref={containerRef} className="m-ascii-canvas-wrapper" aria-hidden="true">
    <canvas ref={ambientRef} className="m-ascii-canvas m-ascii-ambient" />
    <canvas ref={spotlightRef} className="m-ascii-canvas m-ascii-spotlight" />
  </div>;
}
