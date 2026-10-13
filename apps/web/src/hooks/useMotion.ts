import { useEffect, useState, useRef } from 'react';

/**
 * Hook to detect user's preference for reduced motion.
 */
export function usePrefersReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (event: MediaQueryListEvent) => setPrefersReduced(event.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  return prefersReduced;
}

/**
 * Reveals every `data-reveal` element inside the returned ref's element the first
 * time it scrolls into view, by setting `data-shown` on it. The hidden starting
 * state applies only once this runs (`data-motion` on the root), so nothing stays
 * hidden without it. Elements added later, such as a new tab panel, are picked up too.
 */
export function useRevealOnScroll<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T | null>(null);
  const prefersReduced = usePrefersReducedMotion();

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const pending = () => root.querySelectorAll<HTMLElement>('[data-reveal]:not([data-shown])');
    const show = (element: Element) => element.setAttribute('data-shown', '');
    if (prefersReduced || !('IntersectionObserver' in window)) {
      pending().forEach(show);
      return;
    }

    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        show(entry.target);
        observer.unobserve(entry.target);
      }
    }, { rootMargin: '0px 0px -8% 0px' });
    const observeAll = () => pending().forEach(element => observer.observe(element));
    observeAll();
    root.setAttribute('data-motion', '');
    const added = new MutationObserver(observeAll);
    added.observe(root, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      added.disconnect();
      root.removeAttribute('data-motion');
    };
  }, [prefersReduced]);

  return ref;
}

/** True once the element has scrolled into view; stays true. */
export function useInView<T extends HTMLElement = HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || !('IntersectionObserver' in window)) { setInView(true); return; }
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setInView(true); observer.disconnect(); }
    }, { rootMargin: '0px 0px -8% 0px' });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return { ref, inView };
}

/**
 * Hook to reveal elements once when they scroll into view.
 */
export function useScrollReveal<T extends HTMLElement = HTMLDivElement>(threshold = 0.15) {
  const ref = useRef<T | null>(null);
  const [isRevealed, setIsRevealed] = useState(false);
  const prefersReduced = usePrefersReducedMotion();

  useEffect(() => {
    if (prefersReduced) {
      setIsRevealed(true);
      return;
    }

    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsRevealed(true);
          observer.unobserve(node);
        }
      },
      { threshold, rootMargin: '0px 0px -40px 0px' }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [threshold, prefersReduced]);

  return { ref, isRevealed };
}
