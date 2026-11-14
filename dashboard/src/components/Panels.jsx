import Icon from '../Icon.jsx'
import { Badge } from '../ui.jsx'
import { fmtAgo, fmtNum, fmtTime, pmGrade } from '../format.js'

// ───────── 상단 측정 카드 + 작은 추세선 ─────────
export function Sparkline({ values, tone }) {
  const v = values.filter(Number.isFinite)
  if (v.length < 2) return <svg className={`sparkline ${tone}`} viewBox="0 0 84 32" aria-hidden="true" />
  const lo = Math.min(...v)
  const hi = Math.max(...v)
  const span = hi - lo || 1
  const step = 84 / (v.length - 1)
  const pts = v.map((y, i) => `${(i * step).toFixed(1)},${(28 - ((y - lo) / span) * 24).toFixed(1)}`).join(' ')
  return (
    <svg className={`sparkline ${tone}`} viewBox="0 0 84 32" aria-hidden="true">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Metric({ icon, title, value, unit, status, tone, note, series, loading }) {
  return (
    <article className="metric">
      <div className="metric-top">
        <span>
          <Icon name={icon} size={17} />
          {title}
        </span>
        {!loading && <Badge tone={tone}>{status}</Badge>}
      </div>
      <div className="metric-value">
        {loading ? <span className="skeleton" aria-label="불러오는 중" /> : value}
        {!loading && <span>{unit}</span>}
      </div>
      <div className="metric-bottom">
        <span>{note}</span>
        <Sparkline values={series} tone={tone} />
      </div>
    </article>
  )
}

// ───────── 창밖의 공기 ─────────
export function OutdoorPanel({ telemetry: t }) {
  const pm = t?.outdoor_pm25_ugm3
  const grade = pmGrade(pm)
  const src = t?.outdoor_source
  const srcLabel = src === 'SCENARIO' ? '시나리오' : src === 'API' ? '실측 API' : src || '확인 불가'
  return (
    <section className="panel outdoor-panel">
      <div className="panel-head">
        <h2>창밖의 공기</h2>
        <Badge tone={src === 'SCENARIO' ? 'gray' : 'blue'}>{srcLabel}</Badge>
      </div>
      <div className="outdoor-weather">
        <span className="weather-icon">
          <Icon name="cloud-sun" size={51} />
        </span>
        <div>
          <strong>
            {fmtNum(t?.outdoor_temp_c, 1)}
            <span>°C</span>
          </strong>
          <small>바깥 기온</small>
        </div>
      </div>
      <div className="outdoor-reading">
        <span>
          초미세먼지 <small>PM2.5</small>
        </span>
        <strong>
          {fmtNum(pm, 1)}
          <small>µg/m³</small>
          <Badge tone={grade.tone}>{grade.label}</Badge>
        </strong>
      </div>
      <div className="air-scale">
        <span />
        <span />
        <span />
        <span />
        {Number.isFinite(Number(pm)) && <i style={{ left: `${Math.min(98, Math.max(2, Number(pm)))}%` }} />}
      </div>
      <div className="scale-labels">
        <span>좋음</span>
        <span>보통</span>
        <span>나쁨</span>
        <span>매우 나쁨</span>
      </div>
      <div className="outdoor-note">
        <Icon name="info" size={15} />
        <p>
          {src === 'SCENARIO' ? '실험 시나리오로 정한 바깥 값이에요.' : '파이가 받아 온 바깥 공기 값이에요.'}
          <br />
          {t?.ts ? `${fmtTime(t.ts)} 측정` : '측정값 없음'}
        </p>
      </div>
    </section>
  )
}

// ───────── 최근 기록 ─────────
export function EventIcon({ ev }) {
  const name = ev.kind === 'open' ? 'door-open' : ev.kind === 'close' ? 'door-closed' : ev.kind === 'rec' ? 'sparkles' : 'triangle-alert'
  return (
    <span className={`event-icon ${ev.tone}`}>
      <Icon name={name} size={16} />
    </span>
  )
}

export function EventItem({ ev, now }) {
  return (
    <div className="activity-item">
      <EventIcon ev={ev} />
      <div>
        <strong>{ev.title}</strong>
        <p>{ev.detail}</p>
      </div>
      <time dateTime={ev.ts} title={fmtTime(ev.ts)}>
        {fmtAgo(ev.ts, now)}
      </time>
    </div>
  )
}

export function ActivityPanel({ events, now, onMore }) {
  return (
    <section className="panel activity-panel">
      <div className="panel-head">
        <h2>최근 환기 기록</h2>
        <button className="text-button" onClick={onMore}>
          전체 보기
          <Icon name="chevron-right" size={15} />
        </button>
      </div>
      <div className="activity-list">
        {events.slice(0, 3).map((ev) => (
          <EventItem key={ev.key} ev={ev} now={now} />
        ))}
        {!events.length && <p className="muted small">최근 24시간 기록이 없어요.</p>}
      </div>
    </section>
  )
}

// ───────── 장치 정보 (EDGE AI) ─────────
export function InsightPanel({ status, lastSeen, now }) {
  return (
    <section className="insight-panel">
      <span className="insight-icon">
        <Icon name="cpu" size={21} />
      </span>
      <div>
        <span className="eyebrow">EDGE AI</span>
        <h3>판단은 가까이, 기록은 안전하게</h3>
        <p>
          모델 {status?.model_version || '-'} · 시계 {status?.time_synced === false ? '동기화 안 됨' : status ? '동기화됨' : '-'}
          <br />
          마지막 연결 {lastSeen ? fmtAgo(lastSeen, now) : '-'}
        </p>
      </div>
    </section>
  )
}
