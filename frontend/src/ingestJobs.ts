export interface IngestJob {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'error';
  phase: string;
  message: string;
  source_id?: string | null;
  error?: string | null;
}

export type PollOutcome =
  | { state: 'done'; job: IngestJob }
  | { state: 'error'; job: IngestJob }
  | { state: 'unreachable'; detail: string }  // the status endpoint kept failing: the job may still be running
  | { state: 'timeout' }                      // still queued/running when we stopped waiting
  | { state: 'cancelled' };                   // the caller went away (drawer closed, component unmounted)

export interface PollOptions {
  intervalMs?: number;
  timeoutMs?: number;
  maxConsecutiveFailures?: number;
  signal?: AbortSignal;
  onProgress?: (job: IngestJob) => void;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

/**
 * Follow one ingest job to a terminal state. Replaces an unbounded loop that never stopped on unmount and
 * treated a single failed status request as the end of the job: a transient network blip now only counts
 * towards `maxConsecutiveFailures`, and the wait itself is bounded by `timeoutMs`.
 */
export async function pollIngestJob(
  fetchJob: () => Promise<IngestJob>,
  {
    intervalMs = 700,
    timeoutMs = 10 * 60_000,
    maxConsecutiveFailures = 3,
    signal,
    onProgress,
    sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
    now = Date.now,
  }: PollOptions = {},
): Promise<PollOutcome> {
  const deadline = now() + timeoutMs;
  let failures = 0;
  let lastError = '';
  while (true) {
    await sleep(intervalMs);
    if (signal?.aborted) return { state: 'cancelled' };
    try {
      const job = await fetchJob();
      failures = 0;
      if (job.status === 'done') return { state: 'done', job };
      if (job.status === 'error') return { state: 'error', job };
      onProgress?.(job);
    } catch (err) {
      failures += 1;
      lastError = err instanceof Error ? err.message : 'Could not read ingest status';
      if (failures >= maxConsecutiveFailures) return { state: 'unreachable', detail: lastError };
    }
    if (signal?.aborted) return { state: 'cancelled' };
    if (now() >= deadline) return { state: 'timeout' };
  }
}
