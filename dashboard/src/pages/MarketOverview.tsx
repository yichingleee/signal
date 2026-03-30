import { useState } from 'react'
import { GroupGrid } from '../components/groups/GroupGrid'
import { TabBar } from '../components/layout/TabBar'
import { SinglesTable } from '../components/singles/SinglesTable'
import { VWAPTable } from '../components/vwap/VWAPTable'
import type { DashboardSnapshot } from '../types/dashboard'

type MarketTab = 'groups' | 'singles' | 'vwap'

const TABS = [
  { key: 'groups', label: '強勢族群' },
  { key: 'singles', label: '強勢個股' },
  { key: 'vwap', label: 'VWAP 監控' },
] as const

interface Props {
  snapshot: DashboardSnapshot | null
}

export function MarketOverview({ snapshot }: Props) {
  const [tab, setTab] = useState<MarketTab>('groups')

  return (
    <main className="page-content">
      <div className="section-title">Market Overview</div>
      <TabBar
        tabs={TABS.map((item) => ({ ...item }))}
        activeKey={tab}
        onChange={(key) => setTab(key as MarketTab)}
      />
      {!snapshot && <div className="empty-state">Waiting for data...</div>}
      {snapshot && tab === 'groups' && <GroupGrid groups={snapshot.groups} />}
      {snapshot && tab === 'singles' && <SinglesTable singles={snapshot.singles} />}
      {snapshot && tab === 'vwap' && <VWAPTable entries={snapshot.vwap_monitor} />}
    </main>
  )
}
