import type { SignalAMonitorSnapshot } from '../../types/dashboard'

type SignalSide = 'long' | 'short'

function isLongSide(side: 'long' | 'short' | undefined): boolean {
  return side === undefined || side === 'long'
}

function isShortSide(side: 'long' | 'short' | undefined): boolean {
  return side === 'short'
}

export function createSideSnapshot(source: SignalAMonitorSnapshot, side: SignalSide): SignalAMonitorSnapshot {
  const rowFilter = side === 'long' ? isLongSide : isShortSide
  const preparing = source.preparing.filter((row) => rowFilter(row.side))
  const entered = source.entered.filter((row) => rowFilter(row.side))
  const exited = source.exited.filter((row) => rowFilter(row.side))

  return {
    preparing,
    entered,
    exited,
    counters: {
      qualified: preparing.length,
      not_qualified: 0,
      holding: entered.length,
      take_profit: exited.filter((trade) => trade.exit_cause.includes('takeProfit')).length,
      stop_loss: exited.filter((trade) => trade.exit_cause.includes('stopLoss')).length,
      forbidden: 0,
    },
  }
}
