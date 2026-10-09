import { useEffect, useRef, type CSSProperties } from 'react';

const CHAR_SET = ['>', '#', '$', '%', '*', '&', '{', '}', '\\', '|', '@', '/', '+', '-', '=', '(', ')', ':', ';', '0', '8', 'B', 'S', 'X', '~', '<'];
const SPOTLIGHT_RADIUS = 100;

export function AsciiMatrixBackground() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    const hero = container?.closest<HTMLElement>('.m-hero');
    const ctx = canvas?.getContext('2d');
    if (!container || !canvas || !hero || !ctx) return;

    let frame: number | null = null;
    let mutationFrame: number | null = null;
    let disposed = false;
    let revealed = false;
    let inView = true;
    let pointerX = 0;
    let pointerY = 0;
    let cols = 0;
    let rows = 0;
    let symbols: string[] = [];
    let lastMutation = 0;
    const cellWidth = 12;
    const cellHeight = 16;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    const paintCell = (index: number) => {
      const x = (index % cols) * cellWidth;
      const y = Math.floor(index / cols) * cellHeight;
      ctx.clearRect(x, y, cellWidth, cellHeight);
      ctx.fillText(symbols[index], x + cellWidth / 2, y + cellHeight / 2);
    };

    // The grid changes underneath a pointer-local mask, with no ambient visibility.
    const drawGrid = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.font = '500 13px "Geist Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#fff';
      cols = Math.ceil(width / cellWidth);
      rows = Math.ceil(height / cellHeight);
      symbols = Array.from({ length: cols * rows },
        () => CHAR_SET[Math.floor(Math.random() * CHAR_SET.length)]);
      symbols.forEach((_, index) => paintCell(index));
    };

    const stopMutation = () => {
      if (mutationFrame !== null) cancelAnimationFrame(mutationFrame);
      mutationFrame = null;
    };

    const mutate = (now: number) => {
      if (!revealed || !inView || reducedMotion.matches || document.hidden) {
        mutationFrame = null;
        return;
      }
      if (now - lastMutation >= 75) {
        lastMutation = now;
        // Animate the revealed region without redrawing thousands of hidden cells.
        const candidates: number[] = [];
        const startCol = Math.max(0, Math.floor((pointerX - SPOTLIGHT_RADIUS) / cellWidth));
        const endCol = Math.min(cols - 1, Math.ceil((pointerX + SPOTLIGHT_RADIUS) / cellWidth));
        const startRow = Math.max(0, Math.floor((pointerY - SPOTLIGHT_RADIUS) / cellHeight));
        const endRow = Math.min(rows - 1, Math.ceil((pointerY + SPOTLIGHT_RADIUS) / cellHeight));
        for (let row = startRow; row <= endRow; row++) {
          for (let col = startCol; col <= endCol; col++) {
            const x = col * cellWidth + cellWidth / 2;
            const y = row * cellHeight + cellHeight / 2;
            if (Math.hypot(x - pointerX, y - pointerY) <= SPOTLIGHT_RADIUS + cellHeight / 2) {
              candidates.push(row * cols + col);
            }
          }
        }
        for (let i = 0; i < Math.ceil(candidates.length * .25); i++) {
          const pick = i + Math.floor(Math.random() * (candidates.length - i));
          [candidates[i], candidates[pick]] = [candidates[pick], candidates[i]];
          const index = candidates[i];
          const current = CHAR_SET.indexOf(symbols[index]);
          const offset = 1 + Math.floor(Math.random() * (CHAR_SET.length - 1));
          symbols[index] = CHAR_SET[(current + offset) % CHAR_SET.length];
          paintCell(index);
        }
      }
      mutationFrame = requestAnimationFrame(mutate);
    };

    const startMutation = () => {
      if (mutationFrame === null && revealed && inView && !reducedMotion.matches && !document.hidden) {
        lastMutation = performance.now();
        mutationFrame = requestAnimationFrame(mutate);
      }
    };

    const hide = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      revealed = false;
      stopMutation();
      container.style.opacity = '0';
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
        container.style.opacity = '1';
        revealed = true;
        startMutation();
        frame = null;
      });
    };

    const handleVisibility = () => { if (document.hidden) hide(); };
    const handleMotionPreference = () => { if (reducedMotion.matches) stopMutation(); else startMutation(); };
    const visibilityObserver = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      if (!inView) hide();
    });
    visibilityObserver.observe(hero);
    const observer = new ResizeObserver(() => { drawGrid(); hide(); });
    observer.observe(container);
    drawGrid();
    // Font loading can complete after the first draw.
    void document.fonts.ready.then(() => { if (!disposed) drawGrid(); });
    hero.addEventListener('pointermove', reveal, { passive: true });
    hero.addEventListener('pointerleave', hide);
    hero.addEventListener('pointercancel', hide);
    window.addEventListener('resize', drawGrid);
    window.addEventListener('scroll', hide, { passive: true });
    window.addEventListener('blur', hide);
    document.addEventListener('visibilitychange', handleVisibility);
    reducedMotion.addEventListener('change', handleMotionPreference);

    return () => {
      disposed = true;
      hide();
      observer.disconnect();
      visibilityObserver.disconnect();
      hero.removeEventListener('pointermove', reveal);
      hero.removeEventListener('pointerleave', hide);
      hero.removeEventListener('pointercancel', hide);
      window.removeEventListener('resize', drawGrid);
      window.removeEventListener('scroll', hide);
      window.removeEventListener('blur', hide);
      document.removeEventListener('visibilitychange', handleVisibility);
      reducedMotion.removeEventListener('change', handleMotionPreference);
    };
  }, []);

  return <div ref={containerRef} className="m-ascii-canvas-wrapper" aria-hidden="true"
    style={{ '--spotlight-radius': `${SPOTLIGHT_RADIUS}px` } as CSSProperties}>
    <canvas ref={canvasRef} className="m-ascii-canvas" />
  </div>;
}
