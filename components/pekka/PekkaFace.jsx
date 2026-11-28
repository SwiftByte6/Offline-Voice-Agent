"use client";

import Image from "next/image";
import { motion } from "motion/react";
import { useEyeMovement } from "@/hooks/useEyeMovement";
import { PEKKA_STATES } from "@/hooks/usePekkaState";
import PekkaEye from "./PekkaEye";

const ARMOUR_TRANSITION = {
  duration: 0.38,
  ease: [0.22, 1, 0.36, 1],
};

/**
 * Renders PEKKA's black faceplate interior, speech-reactive inner glow & pulse,
 * original left/right eye SVGs, and the lower triangular + central armour bevel SVGs.
 */
export default function PekkaFace({
  status,
  speechEnergy = 0,
  reducedMotion = false,
}) {
  const isSleeping = status === PEKKA_STATES.SLEEPING;
  const isListening = status === PEKKA_STATES.LISTENING;
  const isSuccess = status === PEKKA_STATES.SUCCESS;
  const hideLowerArmour = isSleeping || isSuccess;
  const { leftEye, rightEye, isBlinking } = useEyeMovement({
    status,
    reducedMotion,
  });

  const activeEnergy = isListening && !reducedMotion ? speechEnergy : 0;
  const facePulseScale = isListening && !reducedMotion
    ? Number((0.985 + activeEnergy * 0.03).toFixed(3))
    : 1;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]"
      style={{ backgroundColor: "var(--pekka-faceplate-bg)" }}
    >
      {/* Subtle speech-synchronized shrink/pulse layer preserving exact SVG proportions */}
      <motion.div
        className="relative h-full w-full"
        initial={false}
        animate={{ scale: facePulseScale }}
        transition={
          reducedMotion
            ? { duration: 0.01 }
            : { duration: 0.12, ease: "easeOut" }
        }
      >
        {/* Flanking lower triangular armour plates (hidden in SLEEPING and SUCCESS) */}
        <motion.div
          className="absolute bottom-0 left-1/2 select-none"
          style={{ width: 176, height: 48.6 }}
          initial={false}
          animate={{
            x: "-50%",
            y: hideLowerArmour ? 16 : 0,
            opacity: hideLowerArmour ? 0 : 1,
            scale: hideLowerArmour ? 0.84 : 1,
          }}
          transition={reducedMotion ? { duration: 0.01 } : ARMOUR_TRANSITION}
        >
          <Image
            src="/Lower%20triangular%20armour%20%E2%80%A2%20cleaned.svg"
            width={489}
            height={135}
            unoptimized
            priority
            alt=""
            draggable={false}
            className="h-full w-full object-contain select-none"
          />
        </motion.div>

        {/* Central lower armour bevel / mouth plate (hidden in SLEEPING and SUCCESS) */}
        <motion.div
          className="absolute bottom-0 left-1/2 select-none"
          style={{ width: 74, height: 46.9, transformOrigin: "50% 100%" }}
          initial={false}
          animate={{
            x: "-50%",
            y: hideLowerArmour ? 16 : 0,
            opacity: hideLowerArmour ? 0 : 1,
            scale: hideLowerArmour ? 0.84 : 1,
          }}
          transition={reducedMotion ? { duration: 0.01 } : ARMOUR_TRANSITION}
        >
          <Image
            src="/Lower%20central%20armour%20bevel.svg"
            width={235}
            height={149}
            unoptimized
            priority
            alt=""
            draggable={false}
            className="h-full w-full object-contain select-none"
          />
        </motion.div>

        {/* Original pink PEKKA eyes */}
        <PekkaEye
          side="left"
          isSleeping={isSleeping}
          eyeMotion={leftEye}
          isBlinking={isBlinking}
          reducedMotion={reducedMotion}
        />
        <PekkaEye
          side="right"
          isSleeping={isSleeping}
          eyeMotion={rightEye}
          isBlinking={isBlinking}
          reducedMotion={reducedMotion}
        />
      </motion.div>
    </div>
  );
}
