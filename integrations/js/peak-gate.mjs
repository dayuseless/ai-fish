#!/usr/bin/env node
// Schedule & token-budget gatekeeper for automated agent bridges.
// Distinguishes peak hours vs valley hours, tracks budget, and applies rate-limiting rules.

export class PeakGate {
  /**
   * @param {Object} options
   * @param {number} [options.peakStartHour=9] Peak start hour (0-23)
   * @param {number} [options.peakEndHour=23] Peak end hour (0-23)
   * @param {number} [options.peakMaxTokensPerMinute=20000] Token limit during peak
   * @param {number} [options.valleyMaxTokensPerMinute=60000] Token limit during off-peak
   */
  constructor(options = {}) {
    this.peakStartHour = options.peakStartHour ?? 9;
    this.peakEndHour = options.peakEndHour ?? 23;
    this.peakLimit = options.peakMaxTokensPerMinute ?? 20000;
    this.valleyLimit = options.valleyMaxTokensPerMinute ?? 60000;

    this.tokensUsedInWindow = 0;
    this.windowStart = Date.now();
    this.windowDurationMs = 60 * 1000; // 1 minute sliding/fixed window
  }

  /**
   * Check whether a given date/time is within peak hours.
   * @param {Date} [date=new Date()]
   * @returns {boolean}
   */
  isPeak(date = new Date()) {
    const hour = date.getHours();
    if (this.peakStartHour <= this.peakEndHour) {
      return hour >= this.peakStartHour && hour < this.peakEndHour;
    }
    // Overnight window (e.g. 22:00 to 06:00)
    return hour >= this.peakStartHour || hour < this.peakEndHour;
  }

  getCurrentLimit(date = new Date()) {
    return this.isPeak(date) ? this.peakLimit : this.valleyLimit;
  }

  /**
   * Evaluate whether a request of `tokenCount` is permitted right now.
   * @param {number} tokenCount
   * @returns {{ allowed: boolean, remaining: number, isPeak: boolean, resetInMs: number }}
   */
  check(tokenCount = 0) {
    const now = Date.now();
    if (now - this.windowStart >= this.windowDurationMs) {
      this.tokensUsedInWindow = 0;
      this.windowStart = now;
    }

    const limit = this.getCurrentLimit();
    const remaining = Math.max(0, limit - this.tokensUsedInWindow);
    const allowed = this.tokensUsedInWindow + tokenCount <= limit;
    const resetInMs = Math.max(0, this.windowDurationMs - (now - this.windowStart));

    if (allowed) {
      this.tokensUsedInWindow += tokenCount;
    }

    return {
      allowed,
      remaining: Math.max(0, remaining - (allowed ? tokenCount : 0)),
      isPeak: this.isPeak(),
      resetInMs
    };
  }
}

// CLI usage if run directly
if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('peak-gate.mjs')) {
  const gate = new PeakGate();
  const now = new Date();
  const peak = gate.isPeak(now);
  console.log(`=== Peak Gate Status ===`);
  console.log(`Current Time : ${now.toLocaleTimeString()} (${now.toISOString()})`);
  console.log(`Peak Status  : ${peak ? 'PEAK (High Traffic / Strict Rate Limit)' : 'VALLEY (Off-Peak / Relaxed Limit)'}`);
  console.log(`Limit/min    : ${gate.getCurrentLimit(now)} tokens`);

  const sample = gate.check(1500);
  console.log(`Sample check for 1,500 tokens: ${sample.allowed ? 'ALLOWED' : 'BLOCKED'} (Remaining: ${sample.remaining})`);
}
