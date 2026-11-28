"use client";

import { useSleepingAnimation } from "@/hooks/useSleepingAnimation";
import ZParticles from "./ZParticles";

/**
 * Coordinates the organic sleeping Z particle lifecycle.
 * Stops spawning immediately on wake-up while letting active Zs finish fading out.
 */
export default function SleepingAnimation({ isSleeping, reducedMotion }) {
  const { particles, removeParticle } = useSleepingAnimation({
    isSleeping,
    reducedMotion,
  });

  return (
    <ZParticles particles={particles} onParticleComplete={removeParticle} />
  );
}
