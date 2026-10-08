import { useEffect, useRef } from 'react';

const CHAR_SET = [' ', '>', '#', '$', '%', '*', '&', '{', '}', '\\', '|', '@', '/', '+', '-', '=', '(', ')', ':', ';', '0', '8', 'B', 'S', 'X', '~', '<'];

export function AsciiMatrixBackground() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    let animationFrameId: number;
    let width = 0;
    let height = 0;
    let dpr = 1;

    // Mouse coordinates in CSS pixels
    const mouse = { x: -1000, y: -1000, active: false };

    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
      mouse.active = true;
    };

    const handleMouseLeave = () => {
      mouse.active = false;
      mouse.x = -1000;
      mouse.y = -1000;
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
      width = canvas.parentElement?.clientWidth || window.innerWidth;
      height = canvas.parentElement?.clientHeight || 900;

      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      cols = Math.ceil(width / CELL_W);
      rows = Math.ceil(height / CELL_H);

      // Initialize grid of characters
      grid = new Array(cols * rows);
      for (let i = 0; i < grid.length; i++) {
        grid[i] = CHAR_SET[Math.floor(Math.random() * CHAR_SET.length)];
      }
    };

    resize();
    window.addEventListener('resize', resize);

    let time = 0;
    let lastDraw = 0;
    const fpsInterval = 1000 / 32; // ~32 fps for optimal performance and authentic retro feel

    const render = (now: number) => {
      animationFrameId = requestAnimationFrame(render);

      const elapsed = now - lastDraw;
      if (elapsed < fpsInterval) return;
      lastDraw = now - (elapsed % fpsInterval);

      time += 0.022;

      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, width, height);

      // Randomly mutate a small percentage of characters (matrix shimmer effect)
      const mutateCount = Math.floor(grid.length * 0.035);
      for (let m = 0; m < mutateCount; m++) {
        const idx = Math.floor(Math.random() * grid.length);
        grid[idx] = CHAR_SET[Math.floor(Math.random() * CHAR_SET.length)];
      }

      ctx.font = '12px "Geist Mono", "JetBrains Mono", SFMono-Regular, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      // Wave parameters for the luminous violet nebula flow
      // S-curve flowing down the right-center of the hero (like memorable.sh)
      const baseWaveCenterX = width * 0.64;
      const waveSpread = Math.max(140, width * 0.18);

      for (let r = 0; r < rows; r++) {
        const y = r * CELL_H + CELL_H / 2;
        const normY = y / Math.max(height, 1);

        // Sinusoidal undulating wave path
        const waveX =
          baseWaveCenterX +
          Math.sin(normY * 4.2 + time * 0.8) * (width * 0.09) +
          Math.cos(normY * 2.1 - time * 0.5) * (width * 0.05);

        for (let c = 0; c < cols; c++) {
          const x = c * CELL_W + CELL_W / 2;
          const char = grid[r * cols + c];
          if (!char || char === ' ') continue;

          // Distance to undulating wave center
          const distToWave = Math.abs(x - waveX);
          let intensity = Math.max(0, 1 - distToWave / waveSpread);

          // Additional horizontal secondary glow field
          const centerGlowDist = Math.hypot(x - width * 0.62, y - height * 0.42);
          const radialGlow = Math.max(0, 1 - centerGlowDist / (width * 0.45));
          intensity = Math.max(intensity, radialGlow * 0.85);

          // Mouse proximity reaction
          if (mouse.active) {
            const distToMouse = Math.hypot(x - mouse.x, y - mouse.y);
            if (distToMouse < 180) {
              const mouseBoost = Math.pow(1 - distToMouse / 180, 2) * 0.9;
              intensity = Math.min(1, intensity + mouseBoost);
            }
          }

          // Falloff toward left (hero text area) for maximum contrast
          const leftDamping = Math.min(1, Math.max(0.12, (x / (width * 0.45))));
          const effectiveIntensity = intensity * leftDamping;

          // Render character with tiered colors matching memorable.sh nebula
          if (effectiveIntensity > 0.65) {
            // Hot core: bright lavender / neon violet / white
            const alpha = 0.92 + Math.min(0.08, (effectiveIntensity - 0.65) * 0.3);
            ctx.fillStyle = `rgba(250, 240, 255, ${alpha})`;
          } else if (effectiveIntensity > 0.40) {
            // Bright violet / lavender
            const alpha = 0.72 + (effectiveIntensity - 0.40) * 0.8;
            ctx.fillStyle = `rgba(216, 180, 254, ${alpha})`;
          } else if (effectiveIntensity > 0.20) {
            // Mid violet
            const alpha = 0.45 + (effectiveIntensity - 0.20) * 1.2;
            ctx.fillStyle = `rgba(192, 132, 252, ${alpha})`;
          } else if (effectiveIntensity > 0.08) {
            // Deep purple / indigo
            const alpha = 0.22 + (effectiveIntensity - 0.08) * 1.0;
            ctx.fillStyle = `rgba(168, 85, 247, ${alpha})`;
          } else {
            // Ambient faint matrix glyphs in deep cosmic indigo
            ctx.fillStyle = 'rgba(129, 140, 248, 0.09)';
          }

          ctx.fillText(char, x, y);
        }
      }

      ctx.restore();
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, []);

  return (
    <div className="m-ascii-canvas-wrapper" aria-hidden="true">
      <div className="m-ascii-nebula-glow" />
      <canvas ref={canvasRef} className="m-ascii-canvas" />
    </div>
  );
}
