"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const MAX_ACTIVE_Z = 4;

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

function createZParticle(id) {
  const durationMs = Math.round(randomBetween(1650, 2400));
  const delayMs = Math.round(randomBetween(0, 140));

  return {
    id,
    leftPercent: Number(randomBetween(55, 76).toFixed(1)),
    topPx: Math.round(randomBetween(5, 14)),
    fontSizePx: Number(randomBetween(9.5, 13.5).toFixed(1)),
    dxPx: Number(randomBetween(8, 20).toFixed(1)),
    dyPx: Number(randomBetween(-26, -15).toFixed(1)),
    rotStartDeg: Number(randomBetween(-14, 8).toFixed(1)),
    rotMidDeg: Number(randomBetween(-4, 16).toFixed(1)),
    rotEndDeg: Number(randomBetween(-16, 22).toFixed(1)),
    scaleStart: Number(randomBetween(0.72, 0.88).toFixed(2)),
    scaleEnd: Number(randomBetween(0.98, 1.15).toFixed(2)),
    opacityPeak: Number(randomBetween(0.68, 0.9).toFixed(2)),
    durationMs,
    delayMs,
  };
}

/**
 * Manages randomized, independent sleeping Z particles.
 * Stops spawning immediately when `isSleeping` becomes false while allowing
 * already-active Z particles to finish fading out naturally.
 */
export function useSleepingAnimation({ isSleeping, reducedMotion = false }) {
  const [particles, setParticles] = useState([]);

  const nextIdRef = useRef(1);
  const spawnTimerRef = useRef(null);
  const cleanupTimersRef = useRef(new Map());
  const isSleepingRef = useRef(isSleeping);

  useEffect(() => {
    isSleepingRef.current = isSleeping;
  }, [isSleeping]);

  const removeParticle = useCallback((id) => {
    const timer = cleanupTimersRef.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      cleanupTimersRef.current.delete(id);
    }
    setParticles((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const clearSpawnTimer = useCallback(() => {
    if (spawnTimerRef.current !== null) {
      window.clearTimeout(spawnTimerRef.current);
      spawnTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const timersMap = cleanupTimersRef.current;

    if (!isSleeping || reducedMotion) {
      clearSpawnTimer();
      return;
    }

    let cancelled = false;

    const spawnAndSchedule = () => {
      if (cancelled || !isSleepingRef.current) return;

      const particleId = nextIdRef.current++;
      const particle = createZParticle(particleId);

      setParticles((prev) => {
        const trimmed =
          prev.length >= MAX_ACTIVE_Z ? prev.slice(prev.length - MAX_ACTIVE_Z + 1) : prev;
        return [...trimmed, particle];
      });

      // Fallback cleanup in case CSS animationend is skipped (e.g. background tab).
      const fallbackTimer = window.setTimeout(() => {
        timersMap.delete(particleId);
        setParticles((prev) => prev.filter((item) => item.id !== particleId));
      }, particle.durationMs + particle.delayMs + 250);
      timersMap.set(particleId, fallbackTimer);

      const nextIntervalMs = Math.round(randomBetween(560, 1180));
      spawnTimerRef.current = window.setTimeout(spawnAndSchedule, nextIntervalMs);
    };

    // Quick initial spawn so sleeping feels alive right away.
    spawnTimerRef.current = window.setTimeout(spawnAndSchedule, 240);

    return () => {
      cancelled = true;
      clearSpawnTimer();
    };
  }, [isSleeping, reducedMotion, clearSpawnTimer]);

  useEffect(() => {
    const timersMap = cleanupTimersRef.current;
    return () => {
      clearSpawnTimer();
      timersMap.forEach((timerId) => window.clearTimeout(timerId));
      timersMap.clear();
    };
  }, [clearSpawnTimer]);

  return {
    particles,
    removeParticle,
  };
}
