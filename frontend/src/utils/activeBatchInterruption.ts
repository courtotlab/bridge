export type BatchInterruptionReason = 'navigation' | 'unmount' | 'manual' | 'pagehide';

export interface BatchInterruptionOptions {
  keepalive?: boolean;
  reason?: BatchInterruptionReason;
}

type BatchInterrupter = (options?: BatchInterruptionOptions) => Promise<boolean>;

let activeInterrupter: BatchInterrupter | null = null;
let activeInterruption: Promise<boolean> | null = null;

export function registerActiveBatchInterrupter(interrupter: BatchInterrupter): () => void {
  activeInterrupter = interrupter;
  return () => {
    if (activeInterrupter === interrupter) {
      activeInterrupter = null;
    }
  };
}

export function interruptActiveBatch(
  options: BatchInterruptionOptions = {},
): Promise<boolean> {
  if (!activeInterrupter) return Promise.resolve(false);
  if (activeInterruption) return activeInterruption;

  activeInterruption = activeInterrupter(options)
    .catch(() => false)
    .finally(() => {
      activeInterruption = null;
    });

  return activeInterruption;
}
