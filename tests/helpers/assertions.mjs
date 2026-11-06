/*
 * A deliberately tiny assertion layer.
 *
 * node:test already reports pass/fail well; what it lacks is context.  These
 * wrappers keep the failure message readable in a CI log (the check id, what
 * we expected, what we actually got) without pulling in a matcher library.
 */

export class CheckError extends Error {
  constructor(message, detail) {
    super(message);
    this.name = 'CheckError';
    this.detail = detail;
  }
}

export function ok(value, message) {
  if (!value) throw new CheckError(message);
}

export function equal(actual, expected, message) {
  if (actual !== expected) {
    throw new CheckError(`${message} — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`, {
      actual,
      expected,
    });
  }
}

export function includes(haystack, needle, message) {
  const text = typeof haystack === 'string' ? haystack : JSON.stringify(haystack);
  if (!text.includes(needle)) {
    throw new CheckError(`${message} — ${JSON.stringify(needle)} not found in ${text.slice(0, 400)}`);
  }
}

export function matches(value, regex, message) {
  if (!regex.test(String(value))) throw new CheckError(`${message} — ${JSON.stringify(value)} does not match ${regex}`);
}

export function between(value, min, max, message) {
  if (!(value >= min && value <= max)) throw new CheckError(`${message} — ${value} is outside [${min}, ${max}]`);
}

/** Collects results so a browser run can keep going after one failed check. */
export class Report {
  constructor(name) {
    this.name = name;
    this.checks = [];
    this.startedAt = Date.now();
  }

  pass(id, name, extra = {}) {
    this.checks.push({ id, name, status: 'pass', ms: extra.ms ?? 0, ...extra });
  }

  fail(id, name, error, extra = {}) {
    this.checks.push({
      id,
      name,
      status: 'fail',
      message: error && error.message ? error.message : String(error),
      detail: error && error.detail ? error.detail : undefined,
      ...extra,
    });
  }

  async run(id, name, fn, extra = {}) {
    const t0 = Date.now();
    try {
      const value = await fn();
      this.pass(id, name, { ...extra, ms: Date.now() - t0 });
      return { ok: true, value };
    } catch (error) {
      this.fail(id, name, error, { ...extra, ms: Date.now() - t0 });
      return { ok: false, error };
    }
  }

  get passed() {
    return this.checks.filter((c) => c.status === 'pass').length;
  }

  get failed() {
    return this.checks.filter((c) => c.status === 'fail');
  }

  get total() {
    return this.checks.length;
  }

  toJSON() {
    return {
      suite: this.name,
      startedAt: new Date(this.startedAt).toISOString(),
      durationMs: Date.now() - this.startedAt,
      total: this.total,
      passed: this.passed,
      failed: this.failed.length,
      checks: this.checks,
    };
  }
}
