"use client";

import { motion } from "motion/react";

/**
 * Live bottom-strip transcription / listening status display.
 * Clips cleanly within available width without overlapping PEKKA's eyes.
 */
export default function Transcription({
  text,
  placeholder = "Listening...",
  reducedMotion = false,
}) {
  const hasText = Boolean(text && text.trim());

  return (
    <motion.div
      initial={reducedMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={reducedMotion ? undefined : { opacity: 0 }}
      transition={{ duration: 0.2 }}
      className={`min-w-0 flex-1 overflow-hidden whitespace-nowrap text-[11px] leading-none font-normal tracking-[-0.01em] ${
        hasText ? "pekka-transcript-mask" : ""
      }`}
      style={{ color: "var(--pekka-strip-text-color)" }}
      title={text || placeholder}
    >
      <div className="flex w-full justify-end">
        <span className="inline-block min-w-full text-left">
          {hasText ? text : placeholder}
        </span>
      </div>
    </motion.div>
  );
}
