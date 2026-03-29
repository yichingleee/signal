interface Props {
  mode: 'live' | 'replay'
  connected: boolean
  stale: boolean
  lastUpdate: string
  error: string | null
}

export function StatusBar({ mode, connected, stale, lastUpdate, error }: Props) {
  const connectionText = mode === 'replay'
    ? 'Replay'
    : connected
      ? 'Live'
      : 'Offline'

  return (
    <div className="status-bar">
      <div className="status-main">
        <span className={`status-dot ${connected ? '' : 'disconnected'}`} />
        <span>{connectionText}</span>
        {lastUpdate && <span className="status-time">{lastUpdate}</span>}
      </div>
      {stale && <span className="status-warning">Data may be stale</span>}
      {error && <span className="status-error">{error}</span>}
    </div>
  )
}
