const IDLE_MS = 5 * 60 * 1000

/** Monotonic active time; never fills in an idle or hidden interval. */
export class ActiveStudyClock {
  private total = 0
  private lastTick: number
  private lastInput: number
  private playing = false
  private visible: boolean

  constructor(now: number, visible: boolean) {
    this.visible = visible
    this.lastTick = this.lastInput = now
  }

  read(now: number) {
    now = Math.max(now, this.lastTick)
    if (this.visible) {
      const end = this.playing ? now : Math.min(now, this.lastInput + IDLE_MS)
      this.total += Math.max(0, end - this.lastTick)
    }
    this.lastTick = now
    return Math.floor(this.total)
  }

  interact(now: number) {
    this.read(now)
    this.lastInput = this.lastTick
  }

  setVisible(now: number, visible: boolean) {
    this.read(now)
    if (visible && !this.visible) this.lastInput = this.lastTick
    this.visible = visible
  }

  setPlaying(now: number, playing: boolean) {
    this.read(now)
    this.playing = playing
  }
}

export function formatStudyTime(seconds: number | null | undefined) {
  if (seconds == null) return 'Not tracked'
  const total = Math.max(0, Math.floor(seconds))
  if (total < 60) return `${total}s`
  if (total < 3600) return `${Math.floor(total / 60)}m ${total % 60}s`
  return `${Math.floor(total / 3600)}h ${Math.floor(total % 3600 / 60)}m`
}
