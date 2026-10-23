export class PollingTimeoutError extends Error {
  constructor() {
    super('The operation is taking longer than expected. You can retry without creating a duplicate request.');
  }
}

export interface PollOptions<T> {
  signal: AbortSignal;
  request: (signal: AbortSignal) => Promise<T>;
  isTerminal: (value: T) => boolean;
  timeoutMs?: number;
  initialIntervalMs?: number;
  maxIntervalMs?: number;
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(signal.reason ?? new DOMException('The operation was aborted.', 'AbortError'));
    }, { once: true });
  });
}

export async function pollResource<T>({
  signal,
  request,
  isTerminal,
  timeoutMs = 120_000,
  initialIntervalMs = 800,
  maxIntervalMs = 4_000,
}: PollOptions<T>): Promise<T> {
  const startedAt = Date.now();
  let interval = initialIntervalMs;

  while (!signal.aborted) {
    const value = await request(signal);
    if (isTerminal(value)) return value;
    if (Date.now() - startedAt >= timeoutMs) throw new PollingTimeoutError();
    await wait(interval, signal);
    interval = Math.min(Math.round(interval * 1.5), maxIntervalMs);
  }
  throw signal.reason ?? new DOMException('The operation was aborted.', 'AbortError');
}
