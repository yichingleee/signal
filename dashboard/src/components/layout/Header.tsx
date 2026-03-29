import { NavLink } from 'react-router-dom'

interface Props {
  mode: 'live' | 'replay'
  connected: boolean
  lastUpdate: string
}

export function Header({ mode, connected, lastUpdate }: Props) {
  return (
    <header className="header">
      <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <h1>VWAP Dashboard</h1>
        <nav className="nav-links">
          <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            Market Overview
          </NavLink>
          <NavLink to="/signal-a" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            Signal A 監測
          </NavLink>
        </nav>
      </div>
      <div className="header-right">
        <span className="status-indicator">
          {lastUpdate}
        </span>
        <span className="status-indicator">
          <span className={`status-dot ${connected ? '' : 'disconnected'}`} />
          {mode === 'live' ? (connected ? 'Live' : 'Offline') : 'Replay'}
        </span>
      </div>
    </header>
  )
}
