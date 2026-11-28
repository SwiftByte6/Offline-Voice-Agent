"use client";

import { usePekkaState } from "@/hooks/usePekkaState";

/**
 * Owns the PEKKA state machine transitions and passes controlled state & handlers
 * down to pure presentation components.
 */
export default function StateController({
  successHoldMs,
  onStateChange,
  onTranscript,
  children,
}) {
  const controller = usePekkaState({
    successHoldMs,
    onStateChange,
    onTranscript,
  });

  return children(controller);
}
