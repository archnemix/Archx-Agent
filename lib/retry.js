'use strict';

/*
 * Tiny retry helper for provider calls.
 *
 * A model test (or any provider probe) that fails once for a transient reason
 * (rate limit blip, cold start, 502 from a load balancer in front, timeout) should get
 * a second chance before we tell the user "this model is broken". We retry
 * only on errors that look transient:
 *   - network errors / timeouts (ProxyError 502/504)
 *   - HTTP 408, 429, 5xx
 * and never on 4xx auth/validation errors (retrying a bad key is pointless
 * and would just burn time).
 */

const { ProxyError } = require('./providers/proxy-error.js');

const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504, 529]);

function statusOf(err) {
  if (!err) return null;
  if (err instanceof ProxyError) return err.status || null;
  if (typeof err.status === 'number') return err.status;
  return null;
}

function isRetryable(err) {
  const status = statusOf(err);
  if (status) return RETRYABLE_STATUS.has(status);
  // network-level failures carry no status at all (ECONNRESET, timeouts…)
  return true;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Run fn(); on transient failure retry up to `attempts` times total.
 * @param {Function} fn            async () => result
 * @param {object}   [opts]
 * @param {number}   [opts.attempts=2]  total attempts (1 = no retry)
 * @param {number}   [opts.baseDelayMs=250] delay doubles per retry
 * @param {(err:Error, attempt:number)=>void} [opts.onRetry]
 */
async function withRetry(fn, { attempts = 2, baseDelayMs = 250, onRetry = null } = {}) {
  const total = Math.max(1, Number(attempts) || 1);
  let lastErr;
  for (let attempt = 1; attempt <= total; attempt += 1) {
    try {
      return await fn(attempt);
    } catch (err) {
      lastErr = err;
      if (attempt >= total || !isRetryable(err)) throw err;
      if (onRetry) { try { onRetry(err, attempt); } catch {} }
      await sleep(baseDelayMs * 2 ** (attempt - 1));
    }
  }
  throw lastErr;
}

module.exports = { withRetry, isRetryable, RETRYABLE_STATUS };
