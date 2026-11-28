"use client";

import { useEffect, useRef, useState } from "react";
import { PEKKA_STATES } from "./usePekkaState";

const CENTERED_GAZE = {
  left: { x: 0, y: 0, rot: 0 },
  right: { x: 0, y: 0, rot: 0 },
};

const SLEEPING_EYES = {
  left: { x: 0, y: 0.5, scaleY: 0.88, rot: 0, eyelidClose: 0.52, happySquint: 0 },
  right: { x: 0, y: 0.5, scaleY: 0.88, rot: 0, eyelidClose: 0.52, happySquint: 0 },
};

const HAPPY_EYES = {
  left: { x: 0, y: -1.5, scaleY: 0.94, rot: -2.5, eyelidClose: 0, happySquint: 0.56 },
  right: { x: 0, y: -1.5, scaleY: 0.94, rot: 2.5, eyelidClose: 0, happySquint: 0.56 },
};

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

/**
 * Drives expressive, controllable PEKKA eye shape & mechanical motion across states:
 * - SLEEPING: relaxed sleep-like half-closed slanted lids with still gaze.
 * - LISTENING: lively scanning, occasional micro-jiggle, and crisp blinking.
 * - EXECUTING: focused, calmer scanning and occasional blinking.
 * - SUCCESS: joyful happy-eye squint (`^ ^`) before returning to SLEEPING.
 */
export function useEyeMovement({ status, reducedMotion = false }) {
  const [activeGaze, setActiveGaze] = useState(CENTERED_GAZE);
  const [isBlinking, setIsBlinking] = useState(false);

  const timersRef = useRef(new Set());

  useEffect(() => {
    const timers = timersRef.current;

    const clearAll = () => {
      timers.forEach((id) => window.clearTimeout(id));
      timers.clear();
    };

    const schedule = (fn, delayMs) => {
      const id = window.setTimeout(() => {
        timers.delete(id);
        fn();
      }, delayMs);
      timers.add(id);
      return id;
    };

    clearAll();

    const isAwakeScanning =
      (status === PEKKA_STATES.LISTENING || status === PEKKA_STATES.EXECUTING) &&
      !reducedMotion;

    if (!isAwakeScanning) {
      return clearAll;
    }

    const isListening = status === PEKKA_STATES.LISTENING;
    const maxX = isListening ? 6 : 3;
    const maxY = isListening ? 2 : 1;

    let cancelled = false;

    const triggerJiggle = (baseLeft, baseRight) => {
      const jiggleSteps = [
        { dx: -1.8, dy: -0.9, rot: -1.6, delay: 0 },
        { dx: 1.5, dy: 0.7, rot: 1.4, delay: 65 },
        { dx: -0.8, dy: -0.3, rot: -0.7, delay: 130 },
        { dx: 0, dy: 0, rot: 0, delay: 195 },
      ];

      jiggleSteps.forEach((step) => {
        schedule(() => {
          if (cancelled) return;
          setActiveGaze({
            left: {
              x: Number((baseLeft.x + step.dx).toFixed(2)),
              y: Number((baseLeft.y + step.dy).toFixed(2)),
              rot: step.rot,
            },
            right: {
              x: Number((baseRight.x + step.dx).toFixed(2)),
              y: Number((baseRight.y + step.dy).toFixed(2)),
              rot: -step.rot,
            },
          });
        }, step.delay);
      });
    };

    const scheduleScan = (initialDelay) => {
      const delayMs =
        initialDelay ??
        Math.round(
          randomBetween(isListening ? 680 : 1150, isListening ? 1550 : 2200)
        );

      schedule(() => {
        if (cancelled) return;

        const returnCenter = Math.random() < 0.24;
        const baseX = returnCenter
          ? 0
          : Number(randomBetween(-maxX, maxX).toFixed(2));
        const baseY = returnCenter
          ? 0
          : Number(randomBetween(-maxY, maxY).toFixed(2));

        // Slight independent left/right mechanical offset.
        const deltaX = Number(randomBetween(-1.0, 1.0).toFixed(2));
        const deltaY = Number(randomBetween(-0.45, 0.45).toFixed(2));

        const nextLeft = { x: baseX, y: baseY, rot: 0 };
        const nextRight = {
          x: Number((baseX + deltaX).toFixed(2)),
          y: Number((baseY + deltaY).toFixed(2)),
          rot: 0,
        };

        setActiveGaze({ left: nextLeft, right: nextRight });

        // Occasional quick mechanical jiggle while actively listening.
        if (isListening && Math.random() < 0.35) {
          schedule(() => {
            if (!cancelled) triggerJiggle(nextLeft, nextRight);
          }, 260);
        }

        scheduleScan();
      }, delayMs);
    };

    const scheduleBlink = (initialDelay) => {
      const intervalMs =
        initialDelay ??
        Math.round(
          randomBetween(isListening ? 2000 : 2600, isListening ? 3800 : 4500)
        );

      schedule(() => {
        if (cancelled) return;
        setIsBlinking(true);

        schedule(() => {
          if (cancelled) return;
          setIsBlinking(false);

          // Occasional quick double-blink when listening.
          if (isListening && Math.random() < 0.22) {
            schedule(() => {
              if (cancelled) return;
              setIsBlinking(true);
              schedule(() => {
                if (cancelled) return;
                setIsBlinking(false);
                scheduleBlink();
              }, 125);
            }, 140);
          } else {
            scheduleBlink();
          }
        }, 145);
      }, intervalMs);
    };

    // Wake-up mechanical jiggle right after eyes open, then continuous scan + blink.
    if (isListening) {
      schedule(() => {
        if (!cancelled) {
          triggerJiggle({ x: 0, y: 0, rot: 0 }, { x: 0, y: 0, rot: 0 });
        }
      }, 240);
      scheduleScan(760);
      scheduleBlink(1800);
    } else {
      scheduleScan(120);
      scheduleBlink(2100);
    }

    return () => {
      cancelled = true;
      clearAll();
    };
  }, [status, reducedMotion]);

  if (status === PEKKA_STATES.SLEEPING) {
    return {
      leftEye: SLEEPING_EYES.left,
      rightEye: SLEEPING_EYES.right,
      isBlinking: false,
    };
  }

  if (status === PEKKA_STATES.SUCCESS) {
    return {
      leftEye: HAPPY_EYES.left,
      rightEye: HAPPY_EYES.right,
      isBlinking: false,
    };
  }

  if (reducedMotion) {
    return {
      leftEye: { x: 0, y: 0, scaleY: 1, rot: 0, eyelidClose: 0, happySquint: 0 },
      rightEye: { x: 0, y: 0, scaleY: 1, rot: 0, eyelidClose: 0, happySquint: 0 },
      isBlinking: false,
    };
  }

  const eyelidClose = isBlinking ? 0.94 : 0;
  const scaleY = isBlinking ? 0.92 : 1;

  return {
    leftEye: {
      x: activeGaze.left.x,
      y: activeGaze.left.y,
      scaleY,
      rot: activeGaze.left.rot,
      eyelidClose,
      happySquint: 0,
    },
    rightEye: {
      x: activeGaze.right.x,
      y: activeGaze.right.y,
      scaleY,
      rot: activeGaze.right.rot,
      eyelidClose,
      happySquint: 0,
    },
    isBlinking,
  };
}
