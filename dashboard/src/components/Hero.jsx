import { useEffect, useRef, useState } from 'react'
import Icon from '../Icon.jsx'
import { Badge, Toggle } from '../ui.jsx'
import { getCommand, postActuator, putSettings } from '../api.js'
import { fmtAgo, fmtDuration, fmtHM, fmtNum, pmGrade, REASON_TEXT, RESULT_TEXT, runStart } from '../format.js'

// ───────── AI 환기 추천 (파이가 보낸 recommendation 그대로 표시) ─────────
function viewRec(rec, online, now) {
  if (!rec) {
    return { tone: 'green', badge: '추천 대기', title: '아직 받은 추천이 없어요', desc: '파이가 환기 시점을 판단하면 여기에 표시돼요.' }
  }
  const reason = REASON_TEXT[rec.reason_code] || rec.reason_code || ''
  if (!online) {
    return { tone: 'gray', badge: '연결 대기', title: '장치의 연결을 기다리고 있어요', desc: `마지막으로 받은 추천이에요. ${reason}` }
  }
  if (rec.reason_code === 'PM_VERY_BAD_HOLD') {
    return { tone: 'amber', badge: '환기 보류', title: '지금은 환기를 잠시 미뤄요', desc: '바깥 미세먼지가 매우 나빠요. 바깥 공기가 나아지면 다시 판단해요.' }
  }
  if (!rec.need_vent) {
    return { tone: 'green', badge: '쾌적해요', title: '지금은 좋은 공기를 유지해요', desc: '당장 환기가 필요하지 않다고 판단했어요.' }
  }
  const start = Date.parse(rec.start_ts)
  const end = start + Number(rec.duration_sec || 0) * 1000
  if (Number.isFinite(start) && now > end + 60e3) {
    return { tone: 'gray', badge: '지난 추천', title: '최근 추천한 환기 시간이 지났어요', desc: `${reason}. 새 추천이 오면 바로 바뀌어요.` }
  }
  if (rec.reason_code === 'PM_BAD_SPLIT') {
    return { tone: 'blue', badge: '나눠서 환기', title: '짧게 나누어 환기해 주세요', desc: '바깥 미세먼지가 높아 짧게 환기하고, 닫은 뒤 상태를 다시 확인해요.' }
  }
  if (Number.isFinite(start) && start > now) {
    const mins = Math.ceil((start - now) / 60000)
    return { tone: 'blue', badge: '미리 준비해요', title: `${mins}분 후, 환기를 시작해요`, desc: `${reason}. 기준을 넘기 전에 미리 환기를 준비해요.` }
  }
  return {
    tone: rec.reason_code === 'CO2_OVERRIDE' ? 'amber' : 'blue',
    badge: '지금 환기',
    title: '지금, 공기를 바꿀 시간이에요',
    desc: `${reason}.`,
  }
}

function WindowArt() {
  return (
    <svg className="hero-art" viewBox="0 0 260 220" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="glass" x1="40" y1="20" x2="200" y2="200" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" stopOpacity=".95" />
          <stop offset="1" stopColor="#d1e6ff" stopOpacity=".5" />
        </linearGradient>
      </defs>
      <ellipse cx="139" cy="202" rx="83" ry="9" fill="#2772df" opacity=".06" />
      <path d="M56 35 178 21 201 37v153L76 204l-20-16Z" fill="#e5effd" stroke="#adc9ef" strokeWidth="2" />
      <path d="m76 51 125-14v153L76 204Z" fill="url(#glass)" stroke="#94b9ed" strokeWidth="2" />
      <path d="m87 62 102-11v128L87 191Z" stroke="#bfd3ee" strokeWidth="5" />
      <path d="m138 56 1 128m-51-60 100-11" stroke="#bfd3ee" strokeWidth="4" />
      <path d="m139 56 48 14v111l-48 3Z" fill="#fff" fillOpacity=".85" stroke="#83afe9" strokeWidth="2" />
      <path d="m148 68 30 9v94l-30 2Z" fill="#e5f2ff" />
      <path d="M161 121v14" stroke="#78a2d9" strokeWidth="3" strokeLinecap="round" />
      <g stroke="#6a9ef4" strokeWidth="3" strokeLinecap="round">
        <path d="M29 102h62c20 0 20-25 3-25-8 0-11 4-12 8" />
        <path d="M17 117h102c17 0 19 25 2 25-8 0-11-4-12-8" />
        <path d="M37 132h42" />
      </g>
      <path d="m57 35 19 16m102-30 23 16M56 188l20 16" stroke="#adc9ef" strokeWidth="2" />
      <circle cx="218" cy="76" r="5" fill="#b6d0f6" />
      <circle cx="39" cy="167" r="3" fill="#91b8f4" />
      <path d="m216 144 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z" fill="#82b0f4" />
    </svg>
  )
}

export function RecommendationCard({ rec, online, now, forecast, telemetry }) {
  const v = viewRec(rec, online, now)
  const start = rec ? Date.parse(rec.start_ts) : NaN
  const startText = !rec || !Number.isFinite(start) ? '—' : start > now ? `${Math.ceil((start - now) / 60000)}분 후` : now - start < 60e3 ? '지금' : fmtHM(start)
  const p10 = forecast.find((p) => p.min === 10)
  const pm = pmGrade(telemetry?.outdoor_pm25_ugm3)
  return (
    <section className={`recommendation rec-${v.tone}`}>
      <div className="rec-top">
        <span>
          <Icon name="sparkles" />
          AI 환기 추천
        </span>
        <Badge tone={v.tone}>{v.badge}</Badge>
      </div>
      <div className="rec-body">
        <div>
          <h2>{v.title}</h2>
          <p>{v.desc}</p>
          <div className="recommend-numbers">
            <div>
              <small>권장 시작</small>
              <strong>{startText}</strong>
            </div>
            <span />
            <div>
              <small>권장 환기 시간</small>
              <strong>{rec?.duration_sec ? fmtDuration(rec.duration_sec) : '—'}</strong>
            </div>
          </div>
        </div>
        <WindowArt />
      </div>
      <div className="rec-reasons">
        <span>
          <Icon name="circle-dot" size={14} />
          {p10 ? `+10분 CO₂ ${fmtNum(p10.ppm)} ppm 예상` : '예측 대기 중'}
        </span>
        <span>
          <Icon name="leaf" size={14} />
          바깥 공기 {pm.label}
        </span>
        <span className="rec-age">
          <Icon name="clock-3" size={14} />
          {rec ? `${fmtAgo(rec.ts, now)} 받음` : '-'}
        </span>
      </div>
    </section>
  )
}

// ───────── 환기 창문 (모터 상태 + 수동 열기/닫기 + 자동 환기) ─────────
const NO_RESPONSE_MS = 30000 // SAD 4.2: 30초 전에는 '응답 없음' 을 띄우지 않는다
const DURATIONS = [30, 60, 120, 180, 300, 600]

export function WindowPanel({ actuator, online, settings, canControl, recDuration, outdoorPm, now, notify, onChanged }) {
  const [cmd, setCmd] = useState({ phase: 'idle' })
  const [dur, setDur] = useState(60)
  const sentAt = useRef(0)
  const touched = useRef(false)

  // 추천 시간이 있으면 기본값으로 (사용자가 바꾸기 전까지)
  useEffect(() => {
    if (!touched.current && recDuration) {
      const n = Number(recDuration)
      setDur(DURATIONS.includes(n) ? n : 60)
    }
  }, [recDuration])

  async function send(action) {
    setCmd({ phase: 'pending', action, cmdId: null })
    sentAt.current = Date.now()
    try {
      const r = await postActuator(action, dur)
      setCmd({ phase: 'pending', action, cmdId: r.cmd_id })
    } catch (e) {
      setCmd({ phase: 'error', action, message: e.message })
      notify(`명령을 보내지 못했어요: ${e.message}`, 'error')
    }
  }

  useEffect(() => {
    if (cmd.phase !== 'pending' || !cmd.cmdId) return
    let stop = false
    const tick = async () => {
      try {
        const r = await getCommand(cmd.cmdId)
        if (stop) return
        if (r.status === 'DONE') {
          const sec = ((Date.now() - sentAt.current) / 1000).toFixed(1)
          setCmd((c) => ({ ...c, phase: 'done', result: r.result, state: r.state }))
          notify(r.result === 'OK' ? `창문이 ${r.state === 'OPEN' ? '열렸어요' : '닫혔어요'} (${sec}초)` : `장치가 명령을 처리하지 않았어요: ${RESULT_TEXT[r.result] || r.result}`, r.result === 'OK' ? 'ok' : 'error')
          onChanged?.()
          return
        }
      } catch {
        /* 다음 tick 에 다시 */
      }
      if (!stop && Date.now() - sentAt.current >= NO_RESPONSE_MS) {
        setCmd((c) => ({ ...c, phase: 'timeout' }))
        notify('30초 동안 장치 응답이 없어요. 연결을 확인해 주세요.', 'error')
      }
    }
    tick()
    const t = setInterval(tick, 1000)
    return () => {
      stop = true
      clearInterval(t)
    }
  }, [cmd.phase, cmd.cmdId, notify, onChanged])

  async function toggleAuto(next) {
    try {
      await putSettings({ auto_actuate: next })
      notify(`자동 환기를 ${next ? '켰어요' : '껐어요'}. 파이가 다음 동기화 때 반영해요.`)
      onChanged?.()
    } catch (e) {
      notify(`자동 환기 설정 실패: ${e.message}`, 'error')
    }
  }

  const pending = cmd.phase === 'pending'
  const state = pending ? 'PENDING' : actuator?.state || 'UNKNOWN'
  const stateLabel = { OPEN: '열림', CLOSED: '닫힘', ERROR: '오류', PENDING: '확인 중', UNKNOWN: '기록 없음' }[state] || state
  const stateTone = state === 'OPEN' ? 'blue' : state === 'ERROR' ? 'red' : state === 'PENDING' ? 'amber' : 'gray'
  const auto = Boolean(settings?.effective?.auto_actuate ?? true)
  const disabled = !canControl || !online || pending
  const openFor = actuator?.state === 'OPEN' && actuator?.ts ? fmtAgo(actuator.ts, now).replace(' 전', '') : null

  let summary = '다음 환기를 기다리고 있어요'
  if (pending) summary = `장치의 응답을 기다려요 (${Math.floor((now - sentAt.current) / 1000)}초)`
  else if (state === 'OPEN') summary = '신선한 공기가 들어와요'
  else if (state === 'ERROR') summary = '모터 상태를 확인해 주세요'

  let caption = '열림 시간은 파이가 최대 10분으로 제한해요.'
  let captionClass = ''
  if (Number(outdoorPm) >= 76) {
    caption = '바깥 미세먼지가 매우 나빠요. 열기 명령은 파이가 거부할 수 있어요.'
    captionClass = 'caption-warn'
  }
  if (!canControl) caption = '조회 권한에서는 제어할 수 없어요.'
  else if (!online) caption = '장치가 오프라인이라 제어할 수 없어요.'
  else if (cmd.phase === 'timeout') caption = '응답 없음 (30초). 파이 연결을 확인해 주세요.'
  else if (cmd.phase === 'error') caption = `보내지 못했어요: ${cmd.message}`

  return (
    <section className="panel window-panel">
      <div className="panel-head">
        <h2>환기 창문</h2>
        <Badge tone={stateTone} dot>
          {stateLabel}
        </Badge>
      </div>
      <div className="window-summary">
        <span className={`window-mini ${state === 'OPEN' ? 'is-open' : ''}`}>
          <Icon name={state === 'OPEN' ? 'door-open' : 'door-closed'} size={42} />
        </span>
        <div>
          <strong>{summary}</strong>
          <small>
            {actuator
              ? `${{ AUTO: '자동', MANUAL: '수동', SAFETY: '안전' }[actuator.trigger] || actuator.trigger} · ${openFor ? `열린 지 ${openFor}` : fmtAgo(actuator.ts, now)}`
              : '아직 모터 기록이 없어요'}
          </small>
        </div>
      </div>
      <div className="auto-mode">
        <div>
          <span>자동 환기</span>
          <small>{auto ? '추천 시점에 맞춰 파이가 자동으로 열어요' : '버튼으로 직접 창문을 제어해요'}</small>
        </div>
        <Toggle checked={auto} label="자동 환기" disabled={!canControl || !settings} onChange={toggleAuto} />
      </div>
      <label className="duration-field">
        열림 시간
        <select
          value={dur}
          disabled={disabled}
          onChange={(e) => {
            touched.current = true
            setDur(Number(e.target.value))
          }}
        >
          {DURATIONS.map((s) => (
            <option key={s} value={s}>
              {fmtDuration(s)}
            </option>
          ))}
        </select>
      </label>
      <div className="window-buttons">
        <button className="button primary" disabled={disabled} onClick={() => send('OPEN')}>
          <Icon name="door-open" size={16} />
          열기
        </button>
        <button className="button secondary" disabled={disabled} onClick={() => send('CLOSE')}>
          <Icon name="door-closed" size={16} />
          닫기
        </button>
      </div>
      <p className={`control-caption ${cmd.phase === 'timeout' || cmd.phase === 'error' ? 'caption-alert' : captionClass}`}>{caption}</p>
    </section>
  )
}

// ───────── 실험 배너 (누르면 실험 화면으로) ─────────
export function ExperimentBanner({ settings, now, onOpen }) {
  const eff = settings?.effective || {}
  const runId = eff.run_id && eff.run_id !== 'NONE' ? eff.run_id : null
  const started = runStart(runId)
  const sc = eff.scenario
  const occ = eff.occupancy_set
  const mins = Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 60000)) : null
  return (
    <button className={`exp-banner ${runId ? 'running' : ''}`} onClick={onOpen}>
      <span className="exp-icon">
        <Icon name="flask-conical" size={22} />
      </span>
      <span className="exp-text">
        <span className="exp-title">
          {runId ? '실험 진행 중' : '실험 · 시나리오'}
          {runId ? (
            <span className="badge green">
              <i />
              {mins !== null ? `${mins}분째` : 'RUNNING'}
            </span>
          ) : (
            <span className="badge gray">대기</span>
          )}
        </span>
        <span className="exp-sub">
          {runId ? `${runId} · 시작 ${fmtHM(started)}` : '실험 회차 시작·종료, 바깥 공기 시나리오, 인원 설정'}
          {' · '}
          {sc ? `시나리오 PM2.5 ${sc.pm25} · ${sc.temp}℃ · ${sc.occupancy}명` : '시나리오 없음'}
          {occ !== null && occ !== undefined ? ` · 인원 고정 ${occ}명` : ''}
        </span>
      </span>
      <span className="exp-go">
        실험 열기
        <Icon name="arrow-right" size={15} />
      </span>
    </button>
  )
}
