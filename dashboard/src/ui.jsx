import Icon from './Icon.jsx'

export function Badge({ tone = 'blue', dot = false, children }) {
  return (
    <span className={`badge ${tone}`}>
      {dot && <i />}
      {children}
    </span>
  )
}

export function PanelHead({ title, children }) {
  return (
    <div className="panel-head">
      <h2>{title}</h2>
      {children}
    </div>
  )
}

export function Toggle({ checked, onChange, label, disabled }) {
  return (
    <button
      type="button"
      className={`toggle ${checked ? 'on' : ''}`}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  )
}

export function Warning({ children }) {
  return (
    <div className="state-warning" role="status">
      <Icon name="triangle-alert" />
      {children}
    </div>
  )
}

export function Toast({ message, onClose }) {
  if (!message) return null
  return (
    <div className={`toast ${message.tone === 'error' ? 'error' : ''}`} role="status">
      <Icon name={message.tone === 'error' ? 'triangle-alert' : 'check'} size={17} />
      {message.text}
      <button aria-label="메시지 닫기" onClick={onClose}>
        <Icon name="x" size={15} />
      </button>
    </div>
  )
}
