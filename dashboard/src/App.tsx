import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Header } from './components/layout/Header'
import { StatusBar } from './components/layout/StatusBar'
import { TimelineSlider } from './components/replay/TimelineSlider'
import { MarketOverview } from './pages/MarketOverview'
import { SignalAMonitor } from './pages/SignalAMonitor'
import { useDashboardData } from './hooks/useDashboardData'

export function App() {
  const { snapshot, mode, connected, lastUpdate, stale, error, replay } = useDashboardData()

  return (
    <BrowserRouter>
      <Header mode={mode} connected={connected} lastUpdate={lastUpdate} />
      <StatusBar mode={mode} connected={connected} stale={stale} lastUpdate={lastUpdate} error={error} />
      <Routes>
        <Route
          path="/"
          element={<MarketOverview snapshot={snapshot} />}
        />
        <Route
          path="/signal-a"
          element={<SignalAMonitor snapshot={snapshot} lastUpdate={lastUpdate} />}
        />
      </Routes>
      {mode === 'replay' && replay && (
        <TimelineSlider
          currentTime={replay.currentTime}
          minTime={replay.minTime}
          maxTime={replay.maxTime}
          playing={replay.playing}
          onTogglePlay={() => replay.setPlaying(!replay.playing)}
          onJump={(time) => {
            void replay.jumpTo(time)
          }}
          onStep={(delta) => {
            void replay.step(delta)
          }}
        />
      )}
    </BrowserRouter>
  )
}
