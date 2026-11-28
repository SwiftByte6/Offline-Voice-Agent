"use client";

import Image from "next/image";
import { motion } from "motion/react";

const EYE_ASSETS = {
  left: {
    src: "/EYES%20left.svg",
    width: 182,
    height: 203,
    browTiltDeg: 14,
  },
  right: {
    src: "/EYES%20right.svg",
    width: 182,
    height: 203,
    browTiltDeg: -14,
  },
};

const LAYOUT_TRANSITION = {
  duration: 0.42,
  ease: [0.22, 1, 0.36, 1],
};

/**
 * Renders an original exported PEKKA eye SVG (`EYES left.svg` or `EYES right.svg`)
 * with controllable eye shape (sleep-like slanted lid, happy upward squint, or full open)
 * and mechanical scanning, jiggle, and blinking transitions.
 */
export default function PekkaEye({
  side,
  isSleeping,
  eyeMotion,
  isBlinking,
  reducedMotion,
}) {
  const asset = EYE_ASSETS[side];
  const targetWidth = isSleeping ? 40 : 58;
  const targetHeight = isSleeping ? 44.6 : 64.7;
  const targetOffsetX =
    side === "left" ? (isSleeping ? -24 : -45) : isSleeping ? 24 : 45;
  const targetTop = isSleeping ? 13 : 5;

  const motionTransition = reducedMotion
    ? { duration: 0.01 }
    : {
        x: { duration: 0.18, ease: [0.22, 1, 0.36, 1] },
        y: { duration: 0.2, ease: [0.22, 1, 0.36, 1] },
        rotate: { duration: 0.16, ease: "easeOut" },
        scaleY: {
          duration: isBlinking ? 0.08 : 0.28,
          ease: [0.22, 1, 0.36, 1],
        },
        opacity: { duration: 0.28, ease: "easeOut" },
      };

  const eyelidTransition = reducedMotion
    ? { duration: 0.01 }
    : {
        duration: isBlinking ? 0.085 : 0.32,
        ease: [0.22, 1, 0.36, 1],
      };

  // Convert eyelidClose (0 = open, 1 = closed) to Y translation of the curved upper shutter.
  const shutterTranslatePercent = -100 + eyeMotion.eyelidClose * 100;
  // Convert happySquint (0 = normal, 1 = full cheek raise) to Y translation from bottom up.
  const happyCheekTranslatePercent = 100 - (eyeMotion.happySquint ?? 0) * 100;

  return (
    <motion.div
      aria-hidden="true"
      className="pointer-events-none absolute left-1/2 z-10 select-none"
      initial={false}
      animate={{
        width: targetWidth,
        height: targetHeight,
        top: targetTop,
        x: `calc(-50% + ${targetOffsetX}px)`,
      }}
      transition={reducedMotion ? { duration: 0.01 } : LAYOUT_TRANSITION}
    >
      <motion.div
        className="relative h-full w-full overflow-hidden rounded-[6px]"
        style={{ transformOrigin: "50% 54%" }}
        initial={false}
        animate={{
          x: eyeMotion.x,
          y: eyeMotion.y,
          scaleY: eyeMotion.scaleY,
          rotate: eyeMotion.rot ?? 0,
          opacity: isSleeping ? 0.86 : 1,
        }}
        transition={motionTransition}
      >
        <Image
          src={asset.src}
          width={asset.width}
          height={asset.height}
          unoptimized
          priority
          alt=""
          draggable={false}
          className="h-full w-full object-contain select-none"
        />

        {/* Deeply curved upper eyelid shutter for SLEEPING and awake blink */}
        <motion.div
          className="pointer-events-none absolute -top-[12%] -right-[22%] -left-[22%] h-[112%]"
          style={{
            background:
              "linear-gradient(180deg, var(--pekka-faceplate-bg) 0%, var(--pekka-faceplate-bg) 78%, #0a0c12 100%)",
            borderBottom: "1.5px solid rgba(98, 80, 120, 0.72)",
            borderRadius: "0 0 50% 50% / 0 0 44% 44%",
            transformOrigin: "50% 100%",
          }}
          initial={false}
          animate={{
            y: `${shutterTranslatePercent}%`,
            rotate: isSleeping ? asset.browTiltDeg * 0.45 : asset.browTiltDeg,
            opacity: eyeMotion.eyelidClose > 0.02 ? 1 : 0,
          }}
          transition={eyelidTransition}
        />

        {/* Curved lower cheek/lid arc rising smoothly for happy eyes in SUCCESS */}
        <motion.div
          className="pointer-events-none absolute -right-[22%] -bottom-[14%] -left-[22%] h-[78%]"
          style={{
            background:
              "linear-gradient(0deg, var(--pekka-faceplate-bg) 0%, var(--pekka-faceplate-bg) 74%, #0a0c12 100%)",
            borderTop: "1.5px solid rgba(84, 70, 104, 0.65)",
            borderRadius: "52% 52% 0 0 / 38% 38% 0 0",
            transformOrigin: "50% 0%",
          }}
          initial={false}
          animate={{
            y: `${happyCheekTranslatePercent}%`,
            opacity: (eyeMotion.happySquint ?? 0) > 0.02 ? 1 : 0,
          }}
          transition={eyelidTransition}
        />
      </motion.div>
    </motion.div>
  );
}
