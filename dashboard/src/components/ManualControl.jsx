import { useEffect, useRef, useState } from 'react'
import { getCommand, postActuator } from '../api.js'
import { RESULT_TEXT, STATE_TEXT } from '../format.js'

const NO_RESPONSE_MS = 30000 // SAD 4.2: 30초 전에는 '응답 없음' 을 띄우지 않는다
const POLL_MS = 1000

export default function ManualControl({ onDone }) {
  const [duration, setDuration] = useState(60)
  const [cmd, setCmd] = useState({ phase: 'idle' }) // idle | sending | pending | done | timeout | error
  const sentAt = useRef(0)
  const [elapsed, setElapsed] = useState(0)

  async function send(action) {
    if (action === 'OPEN' && !(duration >= 10 && duration <= 600)) {
      setCmd({ phase: 'error', message: '환기 시간은 10~600초예요' })
      return
    }
    setCmd({ phase: 'sending', action })
    sentAt.current = Date.now()
    try {
      const r = await postActuator(action, Number(duration))
      setCmd({ phase: 'pending', action, cmdId: r.cmd_id })
    } catch (e) {
      setCmd({ phase: 'error', action, message: e.message })
    }
  }

  // 확인 중일 때 1초마다 결과 확인
  useEffect(() => {
    if (cmd.phase !== 'pending') return
    let stop = false
    const tick = async () => {
      const ms = Date.now() - sentAt.current
      setElapsed(ms)
      try {
        const r = await getCommand(cmd.cmdId)
        if (stop) return
        if (r.status === 'DONE') {
          setCmd((c) => ({ ...c, phase: 'done', result: r.result, state: r.state, ms: Date.now() - sentAt.current }))
          onDone?.()
          return
        }
      } catch {
        /* 일시 오류는 다음 tick 에 다시 */
      }
      if (Date.now() - sentAt.current >= NO_RESPONSE_MS) {
        setCmd((c) => ({ ...c, phase: 'timeout' }))
      }
    }
    tick()
    const t = setInterval(tick, POLL_MS)
    return () => {
      stop = true
      clearInterval(t)
    }
  }, [cmd.phase, cmd.cmdId, onDone])

  const busy = cmd.phase === 'sending' || cmd.phase === 'pending'

  return (
    <section className="card">
      <h2>수동 환기</h2>
      <div className="row">
        <label>
          환기 시간(초)
          <input
            type="number"
            min={10}
            max={600}
            step={10}
            value={duration}
            onChange={(e) => setDuration(e.target.value === '' ? '' : Number(e.target.value))}
            disabled={busy}
          />
        </label>
      </div>
      <div className="row">
        <button className="primary" onClick={() => send('OPEN')} disabled={busy}>
          열기 (환기 시작)
        </button>
        <button onClick={() => send('CLOSE')} disabled={busy}>
          닫기
        </button>
      </div>

      <div className="cmd-status" aria-live="polite">
        {cmd.phase === 'sending' && <span>명령 보내는 중…</span>}
        {cmd.phase === 'pending' && <span>확인 중… ({Math.floor(elapsed / 1000)}초)</span>}
        {cmd.phase === 'done' && (
          <span className={cmd.result === 'OK' ? 'good-text' : 'warn-text'}>
            {cmd.result === 'OK' ? '✔' : '!'} {RESULT_TEXT[cmd.result] || cmd.result}
            {cmd.state && ` · 모터 ${STATE_TEXT[cmd.state] || cmd.state}`} ({(cmd.ms / 1000).toFixed(1)}초)
          </span>
        )}
        {cmd.phase === 'timeout' && (
          <span className="crit-text">▲ 응답 없음 (30초). 파이 연결을 확인해 주세요.</span>
        )}
        {cmd.phase === 'error' && <span className="crit-text">▲ 보내지 못했어요: {cmd.message}</span>}
      </div>
      <p className="sub">안전 한도(최대 600초, 4,500ppm, 명령 30초)는 파이에서 지켜요.</p>
    </section>
  )
}
