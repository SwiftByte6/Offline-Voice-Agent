import { isTauri } from "@tauri-apps/api/core";
import { LogicalPosition } from "@tauri-apps/api/dpi";
import { currentMonitor, getCurrentWindow } from "@tauri-apps/api/window";

export const PILL_WINDOW_SIZE = { width: 380, height: 170 };

const TOP_MARGIN_LOGICAL = 20;

export function isTauriRuntime() {
  return typeof window !== "undefined" && isTauri();
}

/**
 * Ensures the native floating window stays above normal windows and hidden from the taskbar.
 */
export async function enforceFloatingWindowBehavior() {
  if (!isTauriRuntime()) return;

  try {
    const appWindow = getCurrentWindow();
    await Promise.all([
      appWindow.setAlwaysOnTop(true),
      appWindow.setSkipTaskbar(true),
    ]);
  } catch (error) {
    console.warn("Unable to apply Tauri floating window behavior:", error);
  }
}

/**
 * Places the floating voice pill near the top-center of the active monitor's work area.
 */
export async function positionInitialFloatingWindow(size = PILL_WINDOW_SIZE) {
  if (!isTauriRuntime()) return;

  try {
    const appWindow = getCurrentWindow();
    const monitor = await currentMonitor();
    if (!monitor) return;

    const scale = monitor.scaleFactor || 1;
    const workPos = monitor.workArea.position.toLogical(scale);
    const workSize = monitor.workArea.size.toLogical(scale);

    const targetX = Math.round(workPos.x + (workSize.width - size.width) / 2);
    const targetY = Math.round(workPos.y + TOP_MARGIN_LOGICAL);

    await appWindow.setPosition(new LogicalPosition(targetX, targetY));
  } catch (error) {
    console.warn("Unable to position initial Tauri window:", error);
  }
}
