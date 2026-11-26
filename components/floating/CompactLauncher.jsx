"use client";

/**
 * Compact idle floating launcher pill.
 * Clicking the NOVA trigger expands into the full voice pill;
 * the outer frame and grip handle native window dragging.
 */
export default function CompactLauncher({ onExpand }) {
  const stopDrag = (event) => {
    event.stopPropagation();
  };

  return (
    <div
      data-tauri-drag-region
      role="region"
      aria-label="NOVA compact launcher"
      className="nova-glass-pill relative flex h-[56px] w-[176px] cursor-grab items-center justify-between rounded-full pl-2 pr-3.5 active:cursor-grabbing"
    >
      <span
        aria-hidden="true"
        className="nova-glass-rim pointer-events-none absolute inset-0 rounded-full"
      />

      <button
        type="button"
        onClick={onExpand}
        onMouseDown={stopDrag}
        onPointerDown={stopDrag}
        aria-label="Expand NOVA voice interface"
        className="group relative z-10 flex cursor-pointer items-center gap-2.5 rounded-full pr-2 outline-none transition-transform duration-150 hover:scale-[1.02] active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-purple-200/70"
      >
        <span className="nova-circle-btn nova-playback-btn relative flex h-10 w-10 items-center justify-center rounded-full text-white transition-transform duration-200 group-hover:scale-105">
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.3"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M5 10v4" />
            <path d="M9.5 6.5v11" />
            <path d="M14.5 4.5v15" />
            <path d="M19 9v6" />
          </svg>
        </span>

        <span className="font-sans text-[13px] font-semibold tracking-[0.16em] text-white/95 drop-shadow-[0_1px_4px_rgba(20,5,45,0.4)]">
          NOVA
        </span>
      </button>

      {/* Dedicated drag grip indicator */}
      <div
        data-tauri-drag-region
        title="Drag NOVA"
        aria-hidden="true"
        className="relative z-10 grid grid-cols-2 gap-[3px] py-2 pl-1.5 opacity-55 transition-opacity hover:opacity-90"
      >
        <span className="h-1 w-1 rounded-full bg-white/90" />
        <span className="h-1 w-1 rounded-full bg-white/90" />
        <span className="h-1 w-1 rounded-full bg-white/90" />
        <span className="h-1 w-1 rounded-full bg-white/90" />
        <span className="h-1 w-1 rounded-full bg-white/90" />
        <span className="h-1 w-1 rounded-full bg-white/90" />
      </div>
    </div>
  );
}
