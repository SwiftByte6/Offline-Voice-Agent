"use client";

import { memo } from "react";

/**
 * Circular translucent purple glass Send button with upward arrow icon.
 */
function SendButton({ onSend, isSentFeedback }) {
  const stopDrag = (event) => {
    event.stopPropagation();
  };

  return (
    <button
      type="button"
      onClick={onSend}
      onMouseDown={stopDrag}
      onPointerDown={stopDrag}
      aria-label="Send voice clip"
      className={`nova-circle-btn nova-send-btn group relative flex h-[50px] w-[50px] shrink-0 cursor-pointer items-center justify-center rounded-full text-white outline-none transition-transform duration-150 ease-out hover:scale-[1.04] active:scale-[0.95] focus-visible:ring-2 focus-visible:ring-purple-200/70 ${
        isSentFeedback ? "ring-2 ring-purple-200/80" : ""
      }`}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-[2.5px] rounded-full border border-white/22"
      />
      <svg
        width="19"
        height="19"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className={`relative z-10 transition-transform duration-150 ${
          isSentFeedback
            ? "-translate-y-0.5 scale-105"
            : "group-hover:-translate-y-0.5"
        }`}
      >
        <path d="M12 19V5" />
        <path d="m6.5 10.5 5.5-5.5 5.5 5.5" />
      </svg>
    </button>
  );
}

export default memo(SendButton);
