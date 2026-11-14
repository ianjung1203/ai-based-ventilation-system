import { useCallback, useEffect, useRef, useState } from 'react'
import { API_URL, DEVICE_ID, getHistory, getLatest, getSettings } from './api.js'
import { buildEvents, fmtDateLong, fmtAgo } from './format.js'
import Icon from './Icon.jsx'
import { Toast } from './ui.jsx'
import Dashboard from './pages/Dashboard.jsx'
import History from './pages/History.jsx'
import Experiment from './pages/Experiment.jsx'
import Settings from './pages/Settings.jsx'

const LATEST_EVERY_MS = 5000 // SAD: 화면 15초 이내
const SETTINGS_EVERY_MS = 30000
const EVENTS_EVERY_MS = 30000
const SPARK_EVERY_MS = 15000

// TODO(D. Cognito): ADMIN 그룹일 때만 true. 지금은 로그인이 없어 모두 제어 가능.
const ROLE = 'ADMIN'

const NAV = [
  ['dashboard', 'layout-dashboard', '대시보드'],
  ['history', 'chart-no-axes-combined', '측정 이력'],
  ['experiment', 'flask-conical', '실험'],
  ['settings', 'settings-2', '장치 설정'],
]
const HEAD = {
  dashboard: ['실내 공기, 한눈에.', '지금의 공기부터 다음 환기까지, 열어조가 함께 살펴볼게요.'],
  history: ['공기의 변화를 기록해요.', '측정값과 환기 기록을 비교하며 흐름을 확인하세요.'],
  experiment: ['조건을 바꾸고, 기록해요.', '바깥 공기 시나리오와 인원을 정하고 실험 회차를 시작·종료하세요.'],
  settings: ['우리 모형에 맞게 설정해요.', '환기 기준과 자동 환기를 실험 환경에 맞게 조정하세요.'],
}
const pageFromHash = () => {
  const p = window.location.hash.slice(1)
  return NAV.some(([id]) => id === p) ? p : 'dashboard'
}

export default function App() {
  const [page, setPage] = useState(pageFromHash)
  const [navOpen, setNavOpen] = useState(false)
  const [latest, setLatest] = useState(null)
  const [settings, setSettings] = useState(null)
  const [events, setEvents] = useState([])
  const [spark, setSpark] = useState([])
  const [error, setError] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [toast, setToast] = useState(null)
  const toastTimer = useRef(null)

  const notify = useCallback((text, tone = 'ok') => {
    clearTimeout(toastTimer.current)
    setToast({ text, tone })
    toastTimer.current = setTimeout(() => setToast(null), 4000)
  }, [])

  const loadLatest = useCallback(async () => {
    if (document.hidden) return
    try {
      setLatest(await getLatest())
      setError(null)
    } catch (e) {
      setError(`최신값을 받지 못했어요 (${e.message})`)
    }
  }, [])

  const loadSettings = useCallback(async () => {
    try {
      setSettings(await getSettings())
    } catch (e) {
      setError(`설정을 받지 못했어요 (${e.message})`)
    }
  }, [])

  const loadEvents = useCallback(async () => {
    if (document.hidden) return
    const to = new Date()
    const from = new Date(to.getTime() - 24 * 3600e3)
    try {
      const [acts, recs] = await Promise.all([
        getHistory('actuator', from.toISOString(), to.toISOString(), 2),
        getHistory('recommendations', from.toISOString(), to.toISOString(), 2),
      ])
      setEvents(buildEvents(acts, recs))
    } catch {
      /* 기록은 실패해도 화면은 계속 */
    }
  }, [])

  // 카드 안의 작은 추세선용 (최근 1시간)
  const loadSpark = useCallback(async () => {
    if (document.hidden) return
    const to = new Date()
    const from = new Date(to.getTime() - 3600e3)
    try {
      setSpark(await getHistory('readings', from.toISOString(), to.toISOString(), 1))
    } catch {
      /* 무시 */
    }
  }, [])

  useEffect(() => {
    loadLatest()
    loadSettings()
    loadEvents()
    loadSpark()
    const timers = [
      setInterval(loadLatest, LATEST_EVERY_MS),
      setInterval(loadSettings, SETTINGS_EVERY_MS),
      setInterval(loadEvents, EVENTS_EVERY_MS),
      setInterval(loadSpark, SPARK_EVERY_MS),
      setInterval(() => setNow(Date.now()), 1000),
    ]
    const onVisible = () => !document.hidden && loadLatest()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      timers.forEach(clearInterval)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [loadLatest, loadSettings, loadEvents, loadSpark])

  useEffect(() => {
    const onHash = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = useCallback((p) => {
    window.location.hash = p
    setPage(p)
    setNavOpen(false)
    window.scrollTo(0, 0)
  }, [])

  const refreshAll = useCallback(() => {
    loadLatest()
    loadSettings()
    loadEvents()
  }, [loadLatest, loadSettings, loadEvents])

  const status = latest?.status
  const online = Boolean(status?.online)
  const lastSeen = status?.last_seen_ts ?? latest?.last_seen_ts ?? status?.last_heartbeat_ts
  const canControl = ROLE === 'ADMIN'
  const ctx = { latest, settings, events, spark, now, online, lastSeen, canControl, notify, refreshAll, go, loadSettings, loadLatest }

  const [title, sub] = HEAD[page]
  const navLabel = NAV.find(([id]) => id === page)?.[2]

  // 브라우저 탭 제목: 페이지 이름 + 오프라인 표시
  useEffect(() => {
    document.title = `${latest && !online ? '● 오프라인 · ' : ''}${navLabel} · 열어조 환기 대시보드`
  }, [navLabel, latest, online])

  return (
    <div className="app-shell">
      {navOpen && <button className="sidebar-scrim" aria-label="메뉴 닫기" onClick={() => setNavOpen(false)} />}
      <aside className={`sidebar ${navOpen ? 'mobile-open' : ''}`}>
        <a className="brand" href="#dashboard" onClick={(e) => (e.preventDefault(), go('dashboard'))}>
          <span className="brand-icon">
            <Icon name="wind" size={25} />
          </span>
          <div>
            <strong>
              열어조<span className="brand-dot">.</span>
            </strong>
            <small>더 나은 공기의 시작</small>
          </div>
        </a>
        <div className="workspace-tag">
          <span className="workspace-icon">
            <Icon name="flask-conical" size={17} />
          </span>
          <div>
            열어조 실험실<small>클라우드 AIoT 프로젝트</small>
          </div>
          <span className="badge gray">LAB</span>
        </div>
        <span className="nav-heading">WORKSPACE</span>
        <nav aria-label="주 메뉴">
          {NAV.map(([id, ic, label]) => (
            <button
              key={id}
              className={`nav-item ${page === id ? 'active' : ''}`}
              aria-current={page === id ? 'page' : undefined}
              onClick={() => go(id)}
            >
              <Icon name={ic} size={19} />
              {label}
              {page === id && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="air-note">
            <div className="air-note-icon">
              <Icon name="leaf" size={22} />
            </div>
            <strong>작은 환기, 좋은 변화</strong>
            <p>
              공기를 확인하는 습관으로
              <br />더 쾌적한 순간을 만들어요.
            </p>
            <span>AI 기반 환기 시점 추천</span>
          </div>
          <div className="profile">
            <span className="avatar">열</span>
            <div>
              <strong>열어조 팀</strong>
              <small>{ROLE === 'ADMIN' ? '관리자' : '조회 전용'} · 로그인 연결 전</small>
            </div>
            <Icon name="shield-check" size={17} />
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button className="icon-button mobile-menu" aria-label="메뉴 열기" onClick={() => setNavOpen(true)}>
              <Icon name="menu" size={22} />
            </button>
            <span>워크스페이스</span>
            <Icon name="chevron-right" size={14} />
            <strong>{navLabel}</strong>
          </div>
          <div className="topbar-actions">
            <span className="topbar-date">{fmtDateLong(now)}</span>
            <span className="top-avatar">열</span>
          </div>
        </header>

        <main id="main">
          <div className="page-heading">
            <div>
              <div className="page-kicker">BREATHE BETTER, LIVE BETTER</div>
              <h1>{title}</h1>
              <p>{sub}</p>
            </div>
            <button className="device-select" onClick={() => go('settings')}>
              <span className={`device-dot ${online ? '' : 'offline'}`} />
              <div>
                <small>현재 디바이스 · {latest ? (online ? '온라인' : '오프라인') : '확인 중'}</small>
                <strong>{DEVICE_ID}</strong>
              </div>
              <Icon name="chevron-down" size={16} />
            </button>
          </div>

          {!API_URL && (
            <div className="state-warning">
              <Icon name="triangle-alert" />
              dashboard/.env 에 VITE_API_URL 을 넣고 npm run dev 를 다시 실행해 주세요.
            </div>
          )}
          {error && (
            <div className="state-warning">
              <Icon name="triangle-alert" />
              {error}
            </div>
          )}

          {page === 'dashboard' && <Dashboard {...ctx} />}
          {page === 'history' && <History {...ctx} />}
          {page === 'experiment' && <Experiment {...ctx} />}
          {page === 'settings' && <Settings {...ctx} />}

          <footer>
            <span>
              <Icon name="wind" size={13} />
              열어조 · AI 기반 실내 환기 시점 추천 시스템
            </span>
            <span>
              마지막 연결 {lastSeen ? fmtAgo(lastSeen, now) : '-'} <i /> 시간은 모두 KST <i /> UI v1.1
            </span>
          </footer>
        </main>
      </div>
      <Toast message={toast} onClose={() => setToast(null)} />
    </div>
  )
}
