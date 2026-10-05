/* 平滑量化的远端进度。小误差通过速度收敛，切歌和跳转直接重定位。 */
class PlaybackClock {
  constructor() { this.reset(); }
  reset() {
    this.position = 0;
    this.sampled = 0;
    this.raw = null;
    this.playing = false;
    this.rate = 1;
    this.error = 0;
    this.duration = 0;
    this.identity = null;
  }
  read(now) {
    const elapsed = this.playing ? Math.max(0, Math.min(1500, now - this.sampled)) : 0;
    // 校正速度最多偏离正常速度 25%，保持时间单调递增。
    const horizon = Math.max(600, Math.abs(this.error) * 4 / this.rate);
    const value = this.position + elapsed * this.rate + this.error * (1 - Math.exp(-elapsed / horizon));
    return Math.max(0, Math.min(this.duration || Infinity, value));
  }
  seek(position, now) {
    this.position = position;
    this.sampled = now;
    this.raw = null;
    this.error = 0;
  }
  update(data, now, force = false) {
    const raw = Math.max(0, data.position || 0), playing = !!data.playing, rate = data.rate || 1;
    const predicted = this.read(now);
    const changed = data.identity != null && data.identity !== this.identity;
    const jump = force || changed || this.raw === null || (!playing && !this.playing && raw !== this.raw) ||
      (raw !== this.raw && (Math.abs(raw - predicted) > 1500 || raw < this.raw - 350));
    const transition = playing !== this.playing || rate !== this.rate;
    if (jump || transition || raw !== this.raw) {
      // 暂停时冻结连续画面；较大的位置变化仍按真实跳转处理。
      this.position = jump ? raw : predicted;
      this.error = jump || !playing ? 0 : raw - predicted;
      this.sampled = now;
    }
    this.raw = raw;
    this.playing = playing;
    this.rate = rate;
    this.duration = data.duration || 0;
    if (data.identity != null) this.identity = data.identity;
  }
}
