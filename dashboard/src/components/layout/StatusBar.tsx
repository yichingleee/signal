import type { LiveFeedStatus } from '../../types/dashboard'

interface Props {
  mode: 'live' | 'replay'
  connected: boolean
  feedStatus: LiveFeedStatus | null
  stale: boolean
  lastUpdate: string
  error: string | null
}

function formatAge(timestamp: string): string {
  const parsed = Date.parse(timestamp)
  if (Number.isNaN(parsed)) return ''
  const ageSeconds = Math.max(0, Math.floor((Date.now() - parsed) / 1000))
  if (ageSeconds < 60) return `${ageSeconds}s`
  return `${Math.floor(ageSeconds / 60)}m`
}

export function StatusBar({ mode, connected, feedStatus, stale, lastUpdate, error }: Props) {
  const socketText = mode === 'replay'
    ? 'Replay'
    : connected
      ? 'Socket connected'
      : 'Socket disconnected / polling'
  const feedAge = feedStatus ? formatAge(feedStatus.last_message_at) : ''
  const feedStale = mode === 'live' && feedStatus?.connected === true && feedAge !== '' && Date.now() - Date.parse(feedStatus.last_message_at) > 5000
  const feedDisconnected = mode === 'live' && feedStatus?.connected === false
  const queueBacklog = (feedStatus?.queue_depth ?? 0) > 1000
  const feedDotClass = feedDisconnected ? 'disconnected' : feedStale || queueBacklog ? 'reconnecting' : ''

  return (
    <div className="status-bar">
      <div className="status-main">
        <span className={`status-dot ${connected ? '' : 'disconnected'}`} />
        <span>{socketText}</span>
        {lastUpdate && <span className="status-time">{lastUpdate}</span>}
      </div>
      {mode === 'live' && feedStatus && (
        <div className="status-main">
          <span className={`status-dot ${feedDotClass}`} />
          <span>{feedStatus.connected ? 'Redis connected' : 'Redis disconnected / retrying'}</span>
          <span>{feedStatus.subscribed_channels} channels</span>
          {feedAge && <span>{feedAge} since feed</span>}
          {feedStatus.reconnect_count > 0 && <span>{feedStatus.reconnect_count} reconnects</span>}
          {feedStatus.queue_depth > 0 && <span>{feedStatus.queue_depth} queued</span>}
          {feedStatus.parse_error_count > 0 && <span>{feedStatus.parse_error_count} parse errors</span>}
          {feedStatus.ignored_message_count > 0 && <span>{feedStatus.ignored_message_count} ignored</span>}
        </div>
      )}
      {stale && <span className="status-warning">Dashboard snapshot stale</span>}
      {feedStale && <span className="status-warning">Redis feed stale</span>}
      {queueBacklog && <span className="status-warning">Redis queue backlog</span>}
      {error && <span className="status-error">{error}</span>}
    </div>
  )
}
