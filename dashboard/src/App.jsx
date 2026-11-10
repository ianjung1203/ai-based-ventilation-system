import { useCallback, useEffect, useState } from 'react'
import { API_URL, DEVICE_ID, getLatest, getSettings } from './api.js'
import { fmtAgo, fmtTime } from './format.js'
import SensorCards from './components/SensorCards.jsx'
import Co2Chart from './components/Co2Chart.jsx'
import StatusCards from './components/StatusCards.jsx'
import ManualControl from './components/ManualControl.jsx'
import ControlPanel from './components/ControlPanel.jsx'

const LATEST_EVERY_MS = 5000 // SAD: 화면 15초 이내 -> 5초마다 /latest
const SETTINGS_EVERY_MS = 30000

// TODO(D. Cognito): ADMIN 그룹일 때만 true. 지금은 로그인이 없어 모두 보임.
const CAN_CONTROL = true

export default function App() {
  const [latest, setLatest] = useState(null)
  const [settings, setSettings] = useState(null)
  const [error, setError] = useState(null)
  const [lastOk, setLastOk] = useState(null)
  const [now, setNow] = useState(Date.now())

  const loadLatest = useCallback(async () => {
    if (document.hidden) return // 탭이 안 보이면 쉬기 (요청 절약)
    try {
      setLatest(await getLatest())
      setError(null)
      setLastOk(Date.now())
    } catch (e) {
      setError(`최신값을 못 받았어요: ${e.message}`)
    }
  }, [])

  const loadSettings = useCallback(async () => {
    try {
      setSettings(await getSettings())
    } catch (e) {
      setError(`설정을 못 받았어요: ${e.message}`)
    }
  }, [])

  useEffect(() => {
    loadLatest()
    loadSettings()
    const a = setInterval(loadLatest, LATEST_EVERY_MS)
    const b = setInterval(loadSettings, SETTINGS_EVERY_MS)
    const c = setInterval(() => setNow(Date.now()), 1000)
    const onVisible = () => !document.hidden && loadLatest()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(a)
      clearInterval(b)
      clearInterval(c)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [loadLatest, loadSettings])

  const status = latest?.status
  const online = status?.online

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>실내 환기 대시보드</h1>
          <div className="sub">
            기기 <b>{DEVICE_ID}</b>
            {status?.model_version && <> · 모델 {status.model_version}</>}
            {status && status.time_synced === false && <span className="warn-text"> · 파이 시계 미동기화</span>}
          </div>
        </div>
        <div className="top-right">
          {status ? (
            <span className={`badge ${online ? 'good' : 'critical'}`}>
              <span aria-hidden="true">{online ? '●' : '▲'}</span> {online ? '온라인' : '오프라인'}
            </span>
          ) : (
            <span className="badge muted">상태 확인 중</span>
          )}
          <div className="sub">
            마지막 heartbeat {status?.last_heartbeat_ts ? fmtAgo(status.last_heartbeat_ts, now) : '-'}
          </div>
          <div className="sub">화면 갱신 {lastOk ? fmtTime(lastOk) : '-'}</div>
        </div>
      </header>

      {!API_URL && (
        <div className="banner critical">dashboard/.env 에 VITE_API_URL 을 넣고 npm run dev 를 다시 실행해 주세요.</div>
      )}
      {error && <div className="banner serious">{error}</div>}

      <SensorCards telemetry={latest?.telemetry} now={now} />

      <Co2Chart latest={latest} settings={settings} />

      <div className="grid-2">
        <StatusCards recommendation={latest?.recommendation} actuator={latest?.actuator} now={now} />
        {CAN_CONTROL && <ManualControl onDone={loadLatest} />}
      </div>

      {CAN_CONTROL && <ControlPanel settings={settings} telemetry={latest?.telemetry} onChanged={loadSettings} />}

      <footer className="foot">
        시간은 모두 한국 시간(KST)으로 표시해요. 서버와 DB 에는 UTC 로 저장돼요.
      </footer>
    </div>
  )
}
