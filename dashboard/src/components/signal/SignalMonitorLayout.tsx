import type { ReactNode } from 'react'
import type { PreparingEntry, ActivePosition, CompletedTrade, SignalCounters, VWAPMonitorEntry } from '../../types/dashboard'
import { CounterBar } from './CounterBar'
import { ActiveCards } from './ActiveCards'
import { ExitedCards } from './ExitedCards'
import { MonitorTable } from './MonitorTable'
import { PreparingCards } from './PreparingCards'

interface Props {
  title: string
  lastUpdate: string
  preparing: PreparingEntry[]
  entered: ActivePosition[]
  exited: CompletedTrade[]
  counters: SignalCounters
  monitorEntries?: VWAPMonitorEntry[]
  beforeLifecycle?: ReactNode
  children?: ReactNode
}

export function SignalMonitorLayout({
  title,
  lastUpdate,
  preparing,
  entered,
  exited,
  counters,
  monitorEntries,
  beforeLifecycle,
  children,
}: Props) {
  return (
    <main className="page-content">
      <div className="section-title">{title}</div>
      <CounterBar counters={counters} lastUpdate={lastUpdate} />
      {beforeLifecycle}
      <PreparingCards entries={preparing} />
      <ActiveCards positions={entered} />
      <ExitedCards trades={exited} />
      {monitorEntries && <MonitorTable entries={monitorEntries} />}
      {children}
    </main>
  )
}
