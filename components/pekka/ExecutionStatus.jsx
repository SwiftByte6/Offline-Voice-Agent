"use client";

import { motion } from "motion/react";

/**
 * Concise bottom-strip status shown during EXECUTING and held cleanly in SUCCESS.
 */
export default function ExecutionStatus({
  statusText,
  isExecuting,
  reducedMotion = false,
}) {
  return (
    <motion.p
      initial={reducedMotion ? false : { opacity: 0, y: 2 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reducedMotion ? undefined : { opacity: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className={`min-w-0 flex-1 truncate text-[11px] leading-none font-normal tracking-[-0.01em] ${
        isExecuting ? "pekka-executing-text" : ""
      }`}
      style={{ color: "var(--pekka-strip-text-color)" }}
      title={statusText}
    >
      {statusText}
    </motion.p>
  );
}
