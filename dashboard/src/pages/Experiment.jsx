import { useState } from 'react'
import Icon from '../Icon.jsx'
import { Badge, PanelHead } from '../ui.jsx'
import { putOccupancy, putRun, putScenario } from '../api.js'
import { fmtDateTime, fmtNum, pmGrade, runStart } from '../format.js'

// 발표·실험용 바깥 공기 시나리오 (Shadow scenario 로 파이에 전달)
const PRESETS = [
  { id: 'clean', title: '바깥 공기 좋음', text: 'PM2.5 10 · 20°C · 2명', tone: 'green', icon: 'leaf', value: { pm25: 10, temp: 20, occupancy: 2 } },
  { id: 'normal', title: '바깥 공기 보통', text: 'PM2.5 25 · 20°C · 2명', tone: 'blue', icon: 'wind', value: { pm25: 25, temp: 20, occupancy: 2 } },
  { id: 'crowd', title: '사람이 많아요', text: 'PM2.5 15 · 22°C · 6명', tone: 'blue', icon: 'users', value: { pm25: 15, temp: 22, occupancy: 6 } },
  { id: 'bad', title: '미세먼지 나쁨', text: 'PM2.5 50 · 18°C → 나눠서 환기', tone: 'amber', icon: 'cloud-sun', value: { pm25: 50, temp: 18, occupancy: 2 } },
  { id: 'verybad', title: '미세먼지 매우 나쁨', text: 'PM2.5 90 · 15°C → 환기 보류', tone: 'red', icon: 'triangle-alert', value: { pm25: 90, temp: 15, occupancy: 2 } },
  { id: 'cold', title: '추운 바깥', text: 'PM2.5 12 · 0°C · 2명', tone: 'gray', icon: 'thermometer', value: { pm25: 12, temp: 0, occupancy: 2 } },
]
const same = (a, b) => a && b && a.pm25 === b.pm25 && a.temp === b.temp && a.occupancy === b.occupancy

export default function Experiment({ settings, latest, now, canControl, notify, loadSettings }) {
  const eff = settings?.effective || {}
  const runId = eff.run_id && eff.run_id !== 'NONE' ? eff.run_id : null
  const started = runStart(runId)
  const scenario = eff.scenario || null
  const occSet = eff.occupancy_set
  const t = latest?.telemetry
  const [note, setNote] = useState('')
  const [form, setForm] = useState({ pm25: '', temp: '', occupancy: '' })
  const [occ, setOcc] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const locked = !canControl || busy

  async function run(label, fn) {
    setBusy(true)
    setErr(null)
    try {
      await fn()
      notify(`${label} 완료. 파이가 다음 동기화 때 반영해요.`)
      await loadSettings()
      return true
    } catch (e) {
      setErr(`${label} 실패: ${e.message}`)
      notify(`${label} 실패: ${e.message}`, 'error')
      return false
    } finally {
      setBusy(false)
    }
  }

  const mins = Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 60000)) : 0
  const formOk = ['pm25', 'temp', 'occupancy'].every((k) => form[k] !== '' && Number.isFinite(Number(form[k])))

  return (
    <>
      <div className="scenario-intro">
        <div className="info-circle">
          <Icon name="flask-conical" size={24} />
        </div>
        <div>
          <h2>실험은 여기서 따로 관리해요</h2>
          <p>
            실험 회차를 시작하면 그동안의 모든 측정값에 run_id 가 붙어 S3 raw/{'{run_id}'}/ 에 따로 모여요.
            시나리오와 인원은 Shadow 로 파이에 전달돼요.
          </p>
        </div>
        {runId ? (
          <Badge tone="green" dot>
            실험 진행 중
          </Badge>
        ) : (
          <Badge tone="gray">대기</Badge>
        )}
      </div>

      {err && <p className="form-error">{err}</p>}

      <div className="exp-grid">
        {/* 실험 회차 */}
        <section className="panel">
          <PanelHead title="실험 회차">
            <Icon name="activity" size={19} />
          </PanelHead>
          {runId ? (
            <div className="run-card running">
              <span className="run-dot" />
              <div>
                <strong>{runId}</strong>
                <small>
                  시작 {fmtDateTime(started)} · {mins}분째 진행 중
                </small>
              </div>
            </div>
          ) : (
            <div className="run-card">
              <div>
                <strong>진행 중인 실험이 없어요</strong>
                <small>시작하면 run_id 가 자동으로 만들어져요 (run-YYYYMMDDTHHMMSSZ)</small>
              </div>
            </div>
          )}
          <label>
            메모 (선택)
            <input type="text" maxLength={200} placeholder="예: E2 인원 4명 · 모형 B" value={note} onChange={(e) => setNote(e.target.value)} disabled={locked || Boolean(runId)} />
          </label>
          <div className="form-footer">
            <span>실험 데이터는 이력 화면에서 run_id 로 확인할 수 있어요.</span>
            {runId ? (
              <button className="button secondary" disabled={locked} onClick={() => run('실험 종료', () => putRun('STOP'))}>
                <Icon name="square" size={15} />
                실험 종료
              </button>
            ) : (
              <button
                className="button primary"
                disabled={locked}
                onClick={async () => (await run('실험 시작', () => putRun('START', note))) && setNote('')}
              >
                <Icon name="play" size={15} />
                실험 시작
              </button>
            )}
          </div>
        </section>

        {/* 인원 */}
        <section className="panel">
          <PanelHead title="실내 인원 직접 정하기">
            <Icon name="users" size={19} />
          </PanelHead>
          <div className="device-facts">
            <div>
              <span>지금 적용</span>
              <strong>{occSet === null || occSet === undefined ? '센서 값 사용' : `${occSet}명으로 고정`}</strong>
            </div>
            <div>
              <span>센서가 본 인원</span>
              <strong>{fmtNum(t?.occupancy)}명</strong>
            </div>
          </div>
          <label className="mt-field">
            고정할 인원
            <div className="input-unit">
              <input type="number" min={0} max={50} value={occ} onChange={(e) => setOcc(e.target.value)} disabled={locked} />
              <span>명</span>
            </div>
          </label>
          <div className="form-footer">
            <button className="button secondary" disabled={locked || occSet === null || occSet === undefined} onClick={() => run('인원 고정 해제', () => putOccupancy(null))}>
              해제
            </button>
            <button className="button primary" disabled={locked || occ === ''} onClick={() => run('인원 고정', () => putOccupancy(parseInt(occ, 10)))}>
              <Icon name="check" size={15} />
              적용
            </button>
          </div>
        </section>
      </div>

      <div className="section-label">
        <h2>
          바깥 공기 시나리오
          {scenario ? <Badge tone="blue">적용 중</Badge> : <Badge tone="gray">없음 · 실제 값 사용</Badge>}
        </h2>
        <span>{scenario ? `PM2.5 ${scenario.pm25} · ${scenario.temp}°C · ${scenario.occupancy}명` : '카드를 누르면 바로 적용돼요'}</span>
      </div>
      <div className="preset-grid">
        {PRESETS.map((p) => {
          const chosen = same(scenario, p.value)
          return (
            <button key={p.id} className={`preset-card ${chosen ? 'chosen' : ''}`} disabled={locked} onClick={() => run(`'${p.title}' 시나리오`, () => putScenario(p.value))}>
              <div>
                <span className={`preset-icon ${p.tone}`}>
                  <Icon name={p.icon} size={23} />
                </span>
                <span className="radio-indicator">{chosen && <Icon name="check" size={13} />}</span>
              </div>
              <h3>{p.title}</h3>
              <p>{p.text}</p>
              <span className="preset-apply">
                {chosen ? '현재 적용 중' : '이 시나리오 적용'}
                <Icon name="arrow-right" size={15} />
              </span>
            </button>
          )
        })}
      </div>

      <section className="panel">
        <PanelHead title="직접 조건 정하기">
          <Icon name="sliders-horizontal" size={19} />
        </PanelHead>
        <div className="form-grid three">
          {[
            ['pm25', '바깥 PM2.5', 'µg/m³', 0, 1000, '1'],
            ['temp', '바깥 기온', '°C', -20, 60, '0.1'],
            ['occupancy', '인원', '명', 0, 50, '1'],
          ].map(([key, label, unit, min, max, step]) => (
            <label key={key}>
              {label}
              <div className="input-unit">
                <input
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  disabled={locked}
                />
                <span>{unit}</span>
              </div>
            </label>
          ))}
        </div>
        {form.pm25 !== '' && (
          <p className="field-hint">
            이 값이면 바깥 공기 <b>{pmGrade(form.pm25).label}</b> 예요. (36 이상 나눠서 환기, 76 이상 환기 보류)
          </p>
        )}
        <div className="form-footer">
          <button className="button secondary" disabled={locked || !scenario} onClick={() => run('시나리오 해제', () => putScenario({}))}>
            시나리오 해제
          </button>
          <button
            className="button primary"
            disabled={locked || !formOk}
            onClick={() =>
              run('시나리오', () => putScenario({ pm25: Number(form.pm25), temp: Number(form.temp), occupancy: parseInt(form.occupancy, 10) }))
            }
          >
            조건 적용하기
            <Icon name="arrow-right" size={16} />
          </button>
        </div>
      </section>
    </>
  )
}
