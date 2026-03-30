import type { VWAPMonitorEntry } from '../../types/dashboard'
import { VWAPTable } from '../vwap/VWAPTable'

export function MonitorTable({ entries }: { entries: VWAPMonitorEntry[] }) {
  // Filter to only symbols with meaningful status
  const filtered = entries.filter((e) => e.status !== '')

  if (filtered.length === 0) return null

  return (
    <div className="signal-section">
      <div className="signal-section-header">明細表</div>
      <VWAPTable entries={filtered} />
    </div>
  )
}
