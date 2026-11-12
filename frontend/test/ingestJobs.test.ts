import { describe, expect, it, vi } from 'vitest';
import { pollIngestJob, type IngestJob } from '../src/ingestJobs';

const job = (status: IngestJob['status'], extra: Partial<IngestJob> = {}): IngestJob =>
  ({ job_id: 'j', status, phase: status, message: status, ...extra });
const noSleep = async () => {};

describe('pollIngestJob', () => {
  it('reports progress then stops on done', async () => {
    const seq = [job('queued'), job('running'), job('done')];
    const progress = vi.fn();
    const out = await pollIngestJob(async () => seq.shift()!, { sleep: noSleep, onProgress: progress });
    expect(out.state).toBe('done');
    expect(progress).toHaveBeenCalledTimes(2);
  });

  it('stops on error and returns the job so the message can be shown', async () => {
    const out = await pollIngestJob(async () => job('error', { error: 'boom' }), { sleep: noSleep });
    expect(out).toMatchObject({ state: 'error', job: { error: 'boom' } });
  });

  it('survives a transient status failure instead of abandoning a running job', async () => {
    const calls = [new Error('network'), job('running'), new Error('network'), job('done')];
    const out = await pollIngestJob(async () => {
      const next = calls.shift()!;
      if (next instanceof Error) throw next;
      return next;
    }, { sleep: noSleep });
    expect(out.state).toBe('done');  // failures are consecutive-only: the running poll reset the counter
  });

  it('gives up as unreachable after consecutive failures, not as an error', async () => {
    const fetchJob = vi.fn(async () => { throw new Error('offline'); });
    const out = await pollIngestJob(fetchJob, { sleep: noSleep, maxConsecutiveFailures: 3 });
    expect(out).toEqual({ state: 'unreachable', detail: 'offline' });
    expect(fetchJob).toHaveBeenCalledTimes(3);
  });

  it('is bounded: it times out instead of polling forever', async () => {
    let t = 0;
    const out = await pollIngestJob(async () => job('running'), {
      sleep: noSleep, timeoutMs: 1000, now: () => (t += 400),
    });
    expect(out.state).toBe('timeout');
  });

  it('stops when the caller aborts (e.g. the drawer unmounted)', async () => {
    const controller = new AbortController();
    const fetchJob = vi.fn(async () => { controller.abort(); return job('running'); });
    const out = await pollIngestJob(fetchJob, { sleep: noSleep, signal: controller.signal });
    expect(out.state).toBe('cancelled');
    expect(fetchJob).toHaveBeenCalledTimes(1);
  });
});
