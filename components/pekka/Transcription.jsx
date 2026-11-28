"use client";

import { motion } from "motion/react";

/**
 * Live bottom-strip transcription display.
 * Clips cleanly within available width and pins newest words into view
 * without ever overlapping PEKKA's eyes.
 */
export default function Transcription({ text, reducedMotion = false }) {
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
      title={text || "Listening"}
    >
      <div className="flex w-full justify-end">
        <span className="inline-block min-w-full text-left">
          {hasText ? `.....${text}` : "Listening..."}
        </span>
      </div>
    </motion.div>
  );
}
