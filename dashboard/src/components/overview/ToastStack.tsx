export interface ToastMessage {
  id: string
  title: string
  detail: string
  kind?: 'vwap' | 'day-high' | 'signal-b'
}

interface Props {
  messages: ToastMessage[]
  className?: string
}

export function ToastStack({ messages, className = 'toast-stack-inline' }: Props) {
  if (messages.length === 0) return null

  return (
    <div className={className}>
      {messages.map((message) => (
        <div key={message.id} className={`toast-card${message.kind ? ` toast-card-${message.kind}` : ''}`}>
          <strong>{message.title}</strong>
          <span>{message.detail}</span>
        </div>
      ))}
    </div>
  )
}
