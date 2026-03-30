function minutesToHHMM(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`
}

function hhmmToMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

interface Props {
  currentTime: string
  minTime: string
  maxTime: string
  playing: boolean
  onTogglePlay: () => void
  onJump: (time: string) => void
  onStep: (deltaMinutes: number) => void
}

export function TimelineSlider({
  currentTime,
  minTime,
  maxTime,
  playing,
  onTogglePlay,
  onJump,
  onStep,
}: Props) {
  const min = hhmmToMinutes(minTime)
  const max = hhmmToMinutes(maxTime)
  const value = hhmmToMinutes(currentTime)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = Number(e.target.value)
    onJump(minutesToHHMM(v))
  }

  return (
    <div className="timeline-bar">
      <button className="timeline-btn" onClick={onTogglePlay}>
        {playing ? '⏸' : '▶'}
      </button>
      <span className="timeline-time">{minutesToHHMM(min)}</span>
      <input
        type="range"
        className="timeline-slider"
        min={min}
        max={max}
        value={value}
        onChange={handleChange}
      />
      <span className="timeline-time">{minutesToHHMM(max)}</span>
      <button className="timeline-btn" onClick={() => onStep(-1)}>-1m</button>
      <span className="timeline-time" style={{ fontWeight: 600, minWidth: 60 }}>
        {minutesToHHMM(value)}
      </span>
      <button className="timeline-btn" onClick={() => onStep(1)}>+1m</button>
    </div>
  )
}
