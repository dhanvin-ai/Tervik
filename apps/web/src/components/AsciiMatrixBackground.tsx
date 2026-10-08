import { useEffect, useRef } from 'react';

const CHAR_SET = [' ', '>', '#', '$', '%', '*', '&', '{', '}', '\\', '|', '@', '/', '+', '-', '=', '(', ')', ':', ';', '0', '8', 'B', 'S', 'X', '~', '<'];

export function AsciiMatrixBackground() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let animationFrameId: number;
    let isVisible = true;
    let width = 0;
    let height = 0;
    let dpr = 1;

    // Mouse coordinates with physics lerp for smoothly smoothed cursor spotlight
    const targetMouse = { x: -1000, y: -1000, active: false };
    const smoothMouse = { x: -1000, y: -1000 };

    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      targetMouse.x = e.clientX - rect.left;
      targetMouse.y = e.clientY - rect.top;
      targetMouse.active = true;
    };

    const handleMouseLeave = () => {
      targetMouse.active = false;
      targetMouse.x = -1000;
      targetMouse.y = -1000;
    };

    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    document.addEventListener('mouseleave', handleMouseLeave);

    const CELL_W = 15;
    const CELL_H = 20;
    let cols = 0;
    let rows = 0;
    let grid: string[] = [];

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = container.clientWidth || window.innerWidth;
      height = container.clientHeight || 1000;

      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      cols = Math.ceil(width / CELL_W);
      rows = Math.ceil(height / CELL_H);

      grid = new Array(cols * rows);
      for (let i = 0; i < grid.length; i++) {
        grid[i] = CHAR_SET[Math.floor(Math.random() * CHAR_SET.length)];
      }
    };

    resize();
    window.addEventListener('resize', resize);

    // Pause RAF loops when scrolled out of view to save 100% CPU/GPU
    const observer = new IntersectionObserver(([entry]) => {
      isVisible = entry.isIntersecting;
    }, { threshold: 0 });
    observer.observe(container);

    let time = 0;
    let lastDraw = 0;
    const fpsInterval = 1000 / 32;

    const render = (now: number) => {
      if (!isVisible) {
        animationFrameId = requestAnimationFrame(render);
        return;
      }

      const elapsed = now - lastDraw;
      if (elapsed < fpsInterval) {
        animationFrameId = requestAnimationFrame(render);
        return;
      }
      lastDraw = now - (elapsed % fpsInterval);

      if (!prefersReducedMotion) {
        time += 0.022;
        // Smoothly lerp mouse spotlight position (softly smoothed cursor spotlight)
        if (targetMouse.active) {
          smoothMouse.x += (targetMouse.x - smoothMouse.x) * 0.09;
          smoothMouse.y += (targetMouse.y - smoothMouse.y) * 0.09;
        } else {
          smoothMouse.x += (-1000 - smoothMouse.x) * 0.09;
          smoothMouse.y += (-1000 - smoothMouse.y) * 0.09;
        }
      }

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);

      // Shimmering mutation on 3% of characters
      if (!prefersReducedMotion) {
        const mutateCount = Math.floor(grid.length * 0.035);
        for (let m = 0; m < mutateCount; m++) {
          const idx = Math.floor(Math.random() * grid.length);
          grid[idx] = CHAR_SET[Math.floor(Math.random() * CHAR_SET.length)];
        }
      }

      ctx.font = '12px "Geist Mono", "JetBrains Mono", SFMono-Regular, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      // 1. Primary Violet Drifting Wave
      const wave1BaseX = width * 0.65;
      const wave1Spread = Math.max(140, width * 0.18);

      // 2. Secondary Cyan / Indigo Drifting Wave (crossing interference)
      const wave2BaseX = width * 0.42;
      const wave2Spread = Math.max(120, width * 0.15);

      for (let r = 0; r < rows; r++) {
        const y = r * CELL_H + CELL_H / 2;
        const normY = y / Math.max(height, 1);

        // Sinusoidal undulating paths
        const wave1X =
          wave1BaseX +
          Math.sin(normY * 4.2 + time * 0.8) * (width * 0.09) +
          Math.cos(normY * 2.1 - time * 0.5) * (width * 0.05);

        const wave2X =
          wave2BaseX +
          Math.cos(normY * 3.6 - time * 0.6) * (width * 0.07) +
          Math.sin(normY * 1.8 + time * 0.4) * (width * 0.04);

        for (let c = 0; c < cols; c++) {
          const x = c * CELL_W + CELL_W / 2;
          const char = grid[r * cols + c];
          if (!char || char === ' ') continue;

          // Wave 1 Intensity (Violet)
          const dist1 = Math.abs(x - wave1X);
          let intensity1 = Math.max(0, 1 - dist1 / wave1Spread);

          // Wave 2 Intensity (Cyan/Indigo)
          const dist2 = Math.abs(x - wave2X);
          let intensity2 = Math.max(0, 1 - dist2 / wave2Spread);

          // Radial center nebula ambient glow
          const centerDist = Math.hypot(x - width * 0.62, y - height * 0.42);
          const radialGlow = Math.max(0, 1 - centerDist / (width * 0.45));
          intensity1 = Math.max(intensity1, radialGlow * 0.85);

          // Softly smoothed cursor spotlight
          let cursorBoost = 0;
          if (smoothMouse.x > -500) {
            const distToMouse = Math.hypot(x - smoothMouse.x, y - smoothMouse.y);
            if (distToMouse < 200) {
              cursorBoost = Math.pow(1 - distToMouse / 200, 2) * 1.1;
            }
          }

          // Left damping for clean hero contrast
          const leftDamping = Math.min(1, Math.max(0.12, (x / (width * 0.46))));
          const effectiveIntensity = (Math.max(intensity1, intensity2 * 0.75) + cursorBoost) * leftDamping;

          // Multi-chromatic tier styling: hot core -> violet -> cyan/indigo -> faint ambient
          if (effectiveIntensity > 0.65) {
            const alpha = 0.92 + Math.min(0.08, (effectiveIntensity - 0.65) * 0.3);
            ctx.fillStyle = cursorBoost > 0.4 ? `rgba(255, 255, 255, ${alpha})` : `rgba(250, 240, 255, ${alpha})`;
          } else if (effectiveIntensity > 0.40) {
            const alpha = 0.72 + (effectiveIntensity - 0.40) * 0.8;
            ctx.fillStyle = intensity2 > intensity1 ? `rgba(147, 197, 253, ${alpha})` : `rgba(216, 180, 254, ${alpha})`;
          } else if (effectiveIntensity > 0.20) {
            const alpha = 0.45 + (effectiveIntensity - 0.20) * 1.2;
            ctx.fillStyle = intensity2 > intensity1 ? `rgba(99, 102, 241, ${alpha})` : `rgba(192, 132, 252, ${alpha})`;
          } else if (effectiveIntensity > 0.08) {
            const alpha = 0.22 + (effectiveIntensity - 0.08) * 1.0;
            ctx.fillStyle = `rgba(168, 85, 247, ${alpha})`;
          } else {
            ctx.fillStyle = 'rgba(129, 140, 248, 0.09)';
          }

          ctx.fillText(char, x, y);
        }
      }

      ctx.restore();

      if (!prefersReducedMotion) {
        animationFrameId = requestAnimationFrame(render);
      }
    };

    if (prefersReducedMotion) {
      render(0);
    } else {
      animationFrameId = requestAnimationFrame(render);
    }

    return () => {
      cancelAnimationFrame(animationFrameId);
      observer.disconnect();
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, []);

  return (
    <div ref={containerRef} className="m-ascii-canvas-wrapper" aria-hidden="true">
      <div className="m-ascii-nebula-glow" />
      <canvas ref={canvasRef} className="m-ascii-canvas" />
    </div>
  );
}
