"use client";

/**
 * Renders individual floating Z particles with randomized trajectory, rotation,
 * scale, duration, and opacity driven by CSS keyframes.
 */
export default function ZParticles({ particles, onParticleComplete }) {
  if (!particles || particles.length === 0) {
    return null;
  }

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-visible"
    >
      {particles.map((particle) => (
        <span
          key={particle.id}
          className="pekka-z-particle"
          onAnimationEnd={() => onParticleComplete(particle.id)}
          style={{
            left: `${particle.leftPercent}%`,
            top: `${particle.topPx}px`,
            fontSize: `${particle.fontSizePx}px`,
            animationDuration: `${particle.durationMs}ms`,
            animationDelay: `${particle.delayMs}ms`,
            "--z-dx": `${particle.dxPx}px`,
            "--z-dy": `${particle.dyPx}px`,
            "--z-rot-start": `${particle.rotStartDeg}deg`,
            "--z-rot-mid": `${particle.rotMidDeg}deg`,
            "--z-rot-end": `${particle.rotEndDeg}deg`,
            "--z-scale-start": particle.scaleStart,
            "--z-scale-end": particle.scaleEnd,
            "--z-opacity-peak": particle.opacityPeak,
          }}
        >
          Z
        </span>
      ))}
    </div>
  );
}
