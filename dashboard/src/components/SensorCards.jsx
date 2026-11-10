import { fmtAgo, fmtNum } from '../format.js'

const STALE_SEC = 30 // telemetry 는 10초(환기 중 5초)마다 -> 30초 넘으면 '지연'

export default function SensorCards({ telemetry: t, now }) {
  const age = t?.ts ? (now - Date.parse(t.ts)) / 1000 : null
  const stale = age !== null && age > STALE_SEC

  const cards = [
    { label: 'CO2', value: fmtNum(t?.co2_ppm), unit: 'ppm', main: true },
    { label: 'PM2.5', value: fmtNum(t?.pm25_ugm3, 1), unit: '㎍/㎥' },
    { label: '온도', value: fmtNum(t?.temp_c, 1), unit: '℃' },
    { label: '습도', value: fmtNum(t?.humidity_pct), unit: '%' },
    { label: '인원', value: fmtNum(t?.occupancy), unit: '명' },
    {
      label: '바깥 공기',
      value: `${fmtNum(t?.outdoor_pm25_ugm3, 1)} ㎍/㎥ · ${fmtNum(t?.outdoor_temp_c, 1)} ℃`,
      unit: t?.outdoor_source ? `(${t.outdoor_source === 'SCENARIO' ? '시나리오' : t.outdoor_source})` : '',
      small: true,
    },
  ]

  return (
    <section className="card">
      <div className="card-head">
        <h2>현재 실내 상태</h2>
        <span className={`sub ${stale ? 'warn-text' : ''}`}>
          {t?.ts ? `측정 ${fmtAgo(t.ts, now)}` : '측정값 없음'}
          {stale && ' · 데이터 지연'}
          {t?.quality && t.quality !== 'OK' && <span className="warn-text"> · 품질 {t.quality}</span>}
          {t?.run_id && t.run_id !== 'NONE' && <> · 실험 {t.run_id}</>}
        </span>
      </div>
      <div className="tiles">
        {cards.map((c) => (
          <div key={c.label} className={`tile ${c.main ? 'tile-main' : ''}`}>
            <div className="tile-label">{c.label}</div>
            <div className={`tile-value ${c.small ? 'tile-small' : ''}`}>
              {c.value} <span className="tile-unit">{c.unit}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
