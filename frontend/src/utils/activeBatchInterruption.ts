export type BatchInterruptionReason = 'navigation' | 'unmount' | 'manual' | 'pagehide';

export interface BatchInterruptionOptions {
  keepalive?: boolean;
  reason?: BatchInterruptionReason;
}

type BatchInterrupter = (options?: BatchInterruptionOptions) => Promise<boolean>;

interface ActiveBatchRegistration {
  interrupter: BatchInterrupter;
  token: object;
}

let activeRegistration: ActiveBatchRegistration | null = null;
let activeInterruption: { promise: Promise<boolean>; token: object } | null = null;

export function registerActiveBatchInterrupter(interrupter: BatchInterrupter): () => void {
  const registration = { interrupter, token: {} };
  activeRegistration = registration;
  return () => {
    if (activeRegistration === registration) {
      activeRegistration = null;
    }
  };
}

export function interruptActiveBatch(
  options: BatchInterruptionOptions = {},
): Promise<boolean> {
  const registration = activeRegistration;
  if (!registration) return Promise.resolve(false);
  if (activeInterruption?.token === registration.token) {
    return activeInterruption.promise;
  }

  const promise = registration.interrupter(options)
    .catch(() => false)
    .finally(() => {
      if (activeInterruption?.token === registration.token) {
        activeInterruption = null;
      }
    });
  activeInterruption = { promise, token: registration.token };

  return promise;
}
