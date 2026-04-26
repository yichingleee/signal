export interface ToastMessage {
  id: string
  title: string
  detail: string
}

export function ToastStack({ messages }: { messages: ToastMessage[] }) {
  if (messages.length === 0) return null

  return (
    <div className="toast-stack">
      {messages.map((message) => (
        <div key={message.id} className="toast-card">
          <strong>{message.title}</strong>
          <span>{message.detail}</span>
        </div>
      ))}
    </div>
  )
}
