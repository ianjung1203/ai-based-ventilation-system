import { useEffect, useState } from 'react'
import Icon from '../Icon.jsx'
import { Badge, PanelHead } from '../ui.jsx'
import { putSettings } from '../api.js'
import { DEVICE_ID } from '../api.js'
import { fmtAgo } from '../format.js'

// Shadow 설정 (SAD 4.2). 안전 한도는 파이 고정이라 여기 없음.
const FIELDS = [
  ['co2_threshold_ppm', '환기 기준 CO₂', 'ppm', 'int'],
  ['target_ppm', '목표 CO₂', 'ppm', 'int'],
  ['co2_override_ppm', '미세먼지 무시 기준 CO₂', 'ppm', 'int'],
  ['ach_per_h', '시간당 환기 횟수 (ACH)', '회/h', 'num'],
  ['g_ppm_per_min', 'CO₂ 발생량', 'ppm/분', 'num'],
]

export default function Settings({ settings, latest, lastSeen, now, canControl, notify, loadSettings }) {
  const eff = settings?.effective || {}
  const reported = settings?.reported || {}
  const [form, setForm] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const status = latest?.status

  // 서버 값으로 폼 채우기 (편집 중이 아닐 때만)
  useEffect(() => {
    if (settings && form === null) setForm(pick(settings.effective))
  }, [settings, form])

  const f = form || pick(eff)
  const disabled = !canControl || busy || !settings

  async function save(e) {
    e.preventDefault()
    const changed = {}
    for (const [k, , , type] of FIELDS) {
      if (f[k] === '' || f[k] === null || f[k] === undefined) continue
      const v = type === 'int' ? parseInt(f[k], 10) : Number(f[k])
      if (v !== eff[k]) changed[k] = v
    }
    if (Boolean(f.auto_actuate) !== Boolean(eff.auto_actuate)) changed.auto_actuate = Boolean(f.auto_actuate)
    if (!Object.keys(changed).length) {
      notify('바뀐 설정이 없어요.')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await putSettings(changed)
      notify('설정을 저장했어요. 파이가 다음 동기화 때 반영해요.')
      await loadSettings()
      setForm(null)
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="settings-layout">
      <form className="panel" onSubmit={save}>
        <PanelHead title="환기 기준">
          <Badge tone="gray">Shadow 로 파이에 전달</Badge>
        </PanelHead>
        <div className="form-grid two">
          {FIELDS.map(([k, label, unit, type]) => (
            <label key={k}>
              {label}
              <div className="input-unit">
                <input
                  type="number"
                  step={type === 'int' ? 10 : 0.1}
                  value={f[k] ?? ''}
                  disabled={disabled}
                  onChange={(e) => setForm({ ...f, [k]: e.target.value })}
                />
                <span>{unit}</span>
              </div>
              <small className="reported">파이 보고값: {reported[k] === undefined ? '아직 없음' : String(reported[k])}</small>
            </label>
          ))}
        </div>
        <p className="field-hint">규칙: 목표 &lt; 환기 기준 &lt; 미세먼지 무시 기준 (ppm 400~4,000). 실제 공간에 쓰기 전에는 별도 검증이 필요해요.</p>
        <div className="settings-row">
          <div>
            <strong>자동 환기</strong>
            <p>추천 시점에 파이가 창문을 자동으로 열어요.</p>
          </div>
          <input
            className="native-checkbox"
            type="checkbox"
            role="switch"
            aria-label="자동 환기"
            checked={Boolean(f.auto_actuate)}
            disabled={disabled}
            onChange={(e) => setForm({ ...f, auto_actuate: e.target.checked })}
          />
        </div>
        {err && (
          <p className="form-error" role="alert">
            {err}
          </p>
        )}
        <div className="form-footer">
          <button type="button" className="button secondary" disabled={disabled || form === null} onClick={() => setForm(null)}>
            변경 취소
          </button>
          <button type="submit" className="button primary" disabled={disabled}>
            <Icon name="check" size={16} />
            설정 저장
          </button>
        </div>
      </form>

      <div className="settings-side">
        <section className="panel">
          <PanelHead title="장치 정보" />
          <div className="device-facts">
            <div>
              <span>장치 ID</span>
              <code>{DEVICE_ID}</code>
            </div>
            <div>
              <span>연결</span>
              <strong>{status ? (status.online ? '온라인' : '오프라인') : '-'}</strong>
            </div>
            <div>
              <span>마지막 연결</span>
              <strong>{lastSeen ? fmtAgo(lastSeen, now) : '-'}</strong>
            </div>
            <div>
              <span>모델 버전</span>
              <strong>{status?.model_version || '-'}</strong>
            </div>
            <div>
              <span>시계 동기화</span>
              <strong>{status?.time_synced === false ? '안 됨' : status ? '됨' : '-'}</strong>
            </div>
            <div>
              <span>Shadow 버전</span>
              <strong>{settings?.shadow_version ?? '-'}</strong>
            </div>
          </div>
        </section>
        <section className="panel safety-panel">
          <Icon name="shield-check" size={25} />
          <h3>장치 보호 규칙</h3>
          <p>
            최대 열림 <strong>600초</strong>
            <br />
            CO₂ 안전 한도 <strong>4,500 ppm</strong>
            <br />
            명령 유효 시간 <strong>30초</strong>
          </p>
          <small>이 값들은 파이에 고정돼 있어 화면이나 서버에서 바꿀 수 없어요.</small>
        </section>
      </div>
    </div>
  )
}

function pick(eff = {}) {
  const o = {}
  for (const [k] of FIELDS) o[k] = eff[k] ?? ''
  o.auto_actuate = eff.auto_actuate ?? true
  return o
}
