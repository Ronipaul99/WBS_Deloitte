export class PollingTimeoutError extends Error {
  constructor() {
    super('Waiting has paused. Check status to continue observing the same request.');
  }
}

export interface PollOptions<T> {
  signal: AbortSignal;
  request: (signal: AbortSignal) => Promise<T>;
  isTerminal: (value: T) => boolean;
  timeoutMs?: number;
  initialIntervalMs?: number;
  maxIntervalMs?: number;
  onUpdate?: (value: T) => void;
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const aborted = () => {
      window.clearTimeout(timer);
      reject(signal.reason ?? new DOMException('The operation was aborted.', 'AbortError'));
    };
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', aborted);
      resolve();
    }, ms);
    if (signal.aborted) aborted();
    else signal.addEventListener('abort', aborted, { once: true });
  });
}

export async function pollResource<T>({
  signal,
  request,
  isTerminal,
  timeoutMs = 120_000,
  initialIntervalMs = 800,
  maxIntervalMs = 4_000,
  onUpdate,
}: PollOptions<T>): Promise<T> {
  const controller = new AbortController();
  const aborted = () => controller.abort(signal.reason);
  if (signal.aborted) aborted();
  else signal.addEventListener('abort', aborted, { once: true });
  const deadline = window.setTimeout(() => controller.abort(new PollingTimeoutError()), timeoutMs);
  let interval = initialIntervalMs;
  const active = controller.signal;
  try {
    while (!active.aborted) {
      // Race the request as well as its signal: even an uncooperative consumer
      // cannot extend the browser deadline or deliver a late update.
      const value = await new Promise<T>((resolve, reject) => {
        const stop = () => reject(active.reason);
        active.addEventListener('abort', stop, { once: true });
        void Promise.resolve().then(() => request(active)).then(resolve, reject)
          .finally(() => active.removeEventListener('abort', stop));
      });
      if (active.aborted) throw active.reason;
      onUpdate?.(value);
      if (isTerminal(value)) return value;
      await wait(interval, active);
      interval = Math.min(Math.round(interval * 1.5), maxIntervalMs);
    }
    throw active.reason;
  } finally {
    window.clearTimeout(deadline);
    signal.removeEventListener('abort', aborted);
  }
}
