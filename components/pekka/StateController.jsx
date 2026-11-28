"use client";

import { usePekkaState } from "@/hooks/usePekkaState";

/**
 * Owns the PEKKA state machine transitions and passes controlled state & handlers
 * down to pure presentation components.
 */
export default function StateController({
  simulate = true,
  successHoldMs,
  onStateChange,
  children,
}) {
  const controller = usePekkaState({
    simulate,
    successHoldMs,
    onStateChange,
  });

  return children(controller);
}
