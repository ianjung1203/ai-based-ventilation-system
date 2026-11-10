import { useEffect, useState } from 'react'
import { putOccupancy, putRun, putScenario, putSettings } from '../api.js'

// Shadow 설정 항목 (SAD 4.2). 안전 한도는 파이 고정이라 여기 없음.
const FIELDS = [
  { key: 'co2_threshold_ppm', label: '환기 시작 기준 CO2 (ppm)', type: 'int' },
  { key: 'target_ppm', label: '목표 CO2 (ppm)', type: 'int' },
  { key: 'co2_override_ppm', label: '미세먼지 무시 기준 CO2 (ppm)', type: 'int' },
  { key: 'ach_per_h', label: '환기 횟수 (회/시간)', type: 'num' },
  { key: 'g_ppm_per_min', label: 'CO2 발생량 (ppm/분)', type: 'num' },
  { key: 'auto_actuate', label: '자동 환기', type: 'bool' },
]

export default function ControlPanel({ settings, telemetry, onChanged }) {
  const eff = settings?.effective || {}
  const reported = settings?.reported || {}
  const [form, setForm] = useState({})
  const [dirty, setDirty] = useState(false)
  const [msg, setMsg] = useState(null)

  const [scn, setScn] = useState({ pm25: '', temp: '', occupancy: '' })
  const [occ, setOcc] = useState('')
  const [note, setNote] = useState('')

  // 서버 값으로 폼 채우기 (편집 중에는 덮어쓰지 않음)
  useEffect(() => {
    if (!settings || dirty) return
    setForm(Object.fromEntries(FIELDS.map((f) => [f.key, eff[f.key]])))
  }, [settings])

  async function run(label, fn) {
    setMsg({ kind: 'info', text: `${label} 저장 중…` })
    try {
      await fn()
      setMsg({ kind: 'good', text: `${label} 저장했어요. 파이가 다음 동기화 때 반영해요.` })
      onChanged?.()
      return true
    } catch (e) {
      setMsg({ kind: 'crit', text: `${label} 실패: ${e.message}` })
      return false
    }
  }

  async function saveSettings() {
    const changed = {}
    for (const f of FIELDS) {
      const v = form[f.key]
      if (v === eff[f.key]) continue
      if (f.type === 'bool') changed[f.key] = Boolean(v)
      else if (v !== '' && v !== null && v !== undefined) changed[f.key] = Number(v)
    }
    if (!Object.keys(changed).length) {
      setMsg({ kind: 'info', text: '바뀐 설정이 없어요.' })
      return
    }
    if (await run('설정', () => putSettings(changed))) setDirty(false)
  }

  function setField(key, value) {
    setDirty(true)
    setForm((f) => ({ ...f, [key]: value }))
  }

  const scenario = eff.scenario
  const runId = eff.run_id || 'NONE'
  const running = runId !== 'NONE'

  return (
    <section className="card">
      <h2>설정 · 시나리오 · 실험</h2>
      {msg && <div className={`banner ${msg.kind === 'crit' ? 'critical' : msg.kind === 'good' ? 'good' : 'muted'}`}>{msg.text}</div>}

      <div className="panel-grid">
        {/* 설정 */}
        <div>
          <h3>환기 설정</h3>
          {FIELDS.map((f) => (
            <label key={f.key} className={f.type === 'bool' ? 'check' : ''}>
              {f.type === 'bool' ? (
                <>
                  <input type="checkbox" checked={Boolean(form[f.key])} onChange={(e) => setField(f.key, e.target.checked)} />
                  {f.label}
                </>
              ) : (
                <>
                  {f.label}
                  <input
                    type="number"
                    step={f.type === 'int' ? 10 : 0.1}
                    value={form[f.key] ?? ''}
                    onChange={(e) => setField(f.key, e.target.value === '' ? '' : Number(e.target.value))}
                  />
                </>
              )}
              <span className="sub hint">파이 보고값: {reported[f.key] === undefined ? '-' : String(reported[f.key])}</span>
            </label>
          ))}
          <div className="row">
            <button className="primary" onClick={saveSettings}>
              설정 저장
            </button>
            {dirty && (
              <button
                onClick={() => {
                  setDirty(false)
                  setForm(Object.fromEntries(FIELDS.map((f) => [f.key, eff[f.key]])))
                }}
              >
                되돌리기
              </button>
            )}
          </div>
          <p className="sub">규칙: 목표 &lt; 시작 기준 &lt; 미세먼지 무시 기준</p>
        </div>

        {/* 시나리오 + 인원 */}
        <div>
          <h3>바깥 공기 시나리오</h3>
          <p className="sub">
            현재: {scenario ? `PM2.5 ${scenario.pm25} · ${scenario.temp}℃ · 인원 ${scenario.occupancy}` : '없음 (실제 값 사용)'}
          </p>
          <label>
            바깥 PM2.5 (㎍/㎥)
            <input type="number" value={scn.pm25} onChange={(e) => setScn({ ...scn, pm25: e.target.value })} />
          </label>
          <label>
            바깥 온도 (℃)
            <input type="number" value={scn.temp} onChange={(e) => setScn({ ...scn, temp: e.target.value })} />
          </label>
          <label>
            인원 (명)
            <input type="number" value={scn.occupancy} onChange={(e) => setScn({ ...scn, occupancy: e.target.value })} />
          </label>
          <div className="row">
            <button
              className="primary"
              disabled={scn.pm25 === '' || scn.temp === '' || scn.occupancy === ''}
              onClick={() =>
                run('시나리오', () =>
                  putScenario({ pm25: Number(scn.pm25), temp: Number(scn.temp), occupancy: parseInt(scn.occupancy, 10) }),
                )
              }
            >
              시나리오 적용
            </button>
            <button onClick={() => run('시나리오 해제', () => putScenario({}))}>해제</button>
          </div>

          <h3 className="mt">인원 직접 설정</h3>
          <p className="sub">
            현재: {eff.occupancy_set === null || eff.occupancy_set === undefined ? '없음 (센서 값 사용)' : `${eff.occupancy_set}명`}
            {telemetry?.occupancy !== undefined && ` · 센서 ${telemetry.occupancy}명`}
          </p>
          <div className="row">
            <input type="number" min={0} max={50} value={occ} onChange={(e) => setOcc(e.target.value)} placeholder="명" />
            <button className="primary" disabled={occ === ''} onClick={() => run('인원', () => putOccupancy(parseInt(occ, 10)))}>
              적용
            </button>
            <button onClick={() => run('인원 해제', () => putOccupancy(null))}>해제</button>
          </div>
        </div>

        {/* 실험 */}
        <div>
          <h3>실험</h3>
          <p>
            {running ? (
              <span className="badge good">
                <span aria-hidden="true">●</span> 진행 중
              </span>
            ) : (
              <span className="badge muted">진행 중인 실험 없음</span>
            )}
          </p>
          {running && <p className="sub">run_id: {runId}</p>}
          <label>
            메모 (선택)
            <input type="text" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} disabled={running} />
          </label>
          <div className="row">
            <button className="primary" disabled={running} onClick={async () => (await run('실험 시작', () => putRun('START', note))) && setNote('')}>
              실험 시작
            </button>
            <button disabled={!running} onClick={() => run('실험 종료', () => putRun('STOP'))}>
              실험 종료
            </button>
          </div>
          <p className="sub">실험 중 데이터는 S3 raw/{'{run_id}'}/ 아래에 따로 모여요.</p>
        </div>
      </div>
    </section>
  )
}
