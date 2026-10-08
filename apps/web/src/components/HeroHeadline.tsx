import { usePrefersReducedMotion } from '../hooks/useMotion';

interface HeroHeadlineProps {
  line1?: string;
  line2?: string;
}

export function HeroHeadline({
  line1 = 'Procedural Intelligence &',
  line2 = 'Failure Detection For Agents.',
}: HeroHeadlineProps) {
  const prefersReduced = usePrefersReducedMotion();

  const wordsLine1 = line1.split(' ');
  const wordsLine2 = line2.split(' ');

  let globalIndex = 0;

  return (
    <h1 className="m-hero-title">
      <span className="m-title-line">
        {wordsLine1.map((word, i) => {
          const delay = prefersReduced ? 0 : globalIndex++ * 0.04;
          return (
            <span
              key={i}
              className="m-title-word"
              style={{ animationDelay: `${delay}s` }}
            >
              {word}
            </span>
          );
        })}
      </span>
      <br />
      <span className="m-title-line">
        {wordsLine2.map((word, i) => {
          const delay = prefersReduced ? 0 : globalIndex++ * 0.04;
          return (
            <span
              key={i}
              className="m-title-word"
              style={{ animationDelay: `${delay}s` }}
            >
              {word}
            </span>
          );
        })}
      </span>
    </h1>
  );
}
