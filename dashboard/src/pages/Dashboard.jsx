import { useMemo, useState } from 'react'
import Icon from '../Icon.jsx'
import { Badge, Warning } from '../ui.jsx'
import { fmtAgo, fmtNum, pmGrade, predictionPoints } from '../format.js'
import Co2Chart, { ChartLegend } from '../components/Co2Chart.jsx'
import { ActivityPanel, InsightPanel, Metric, OutdoorPanel } from '../components/Panels.jsx'
import { ExperimentBanner, RecommendationCard, WindowPanel } from '../components/Hero.jsx'

const STALE_SEC = 30 // telemetry 10초(환기 중 5초) 주기 -> 30초 넘으면 지연
const RANGES = { '30분': 30 * 60e3, '1시간': 60 * 60e3 }

const comfort = (v, lo, hi) => {
  const n = Number(v)
  if (v === null || v === undefined || !Number.isFinite(n)) return { label: '확인 불가', tone: 'gray' }
  return n >= lo && n <= hi ? { label: '적정', tone: 'green' } : { label: '확인', tone: 'amber' }
}

export default function Dashboard({ latest, settings, events, spark, now, online, lastSeen, canControl, notify, refreshAll, go }) {
  const [range, setRange] = useState('30분')
  const t = latest?.telemetry
  const thr = Number(settings?.effective?.co2_threshold_ppm ?? 1000)
  const forecast = useMemo(() => predictionPoints(latest?.prediction), [latest])
  const series = (key) => spark.map((r) => Number(r[key]))
  const age = t?.ts ? (now - Date.parse(t.ts)) / 1000 : null
  const co2 = Number(t?.co2_ppm)
  const co2Ok = t && Number.isFinite(co2)
  const pmIn = pmGrade(t?.pm25_ugm3)
  const temp = comfort(t?.temp_c, 18, 26)
  const hum = comfort(t?.humidity_pct, 40, 60)
  const loading = !latest

  return (
    <>
      {latest && !online && (
        <Warning>장치 연결이 끊겼어요. 마지막으로 받은 값을 보여 주며, 원격 제어를 막아 두었어요.</Warning>
      )}
      {online && age !== null && age > STALE_SEC && <Warning>측정값이 {Math.round(age)}초 동안 갱신되지 않았어요.</Warning>}
      {t?.quality && t.quality !== 'OK' && <Warning>센서 품질 상태가 {t.quality} 예요. 측정값을 확인해 주세요.</Warning>}

      <ExperimentBanner settings={settings} now={now} onOpen={() => go('experiment')} />

      <div className="section-label">
        <h2>
          현재 실내 공기질
          <Badge tone={latest ? (online ? 'green' : 'gray') : 'gray'} dot>
            {latest ? (online ? '온라인' : '오프라인') : '확인 중'}
          </Badge>
        </h2>
        <span>
          <Icon name="users" size={12} />
          인원 {fmtNum(t?.occupancy)}명
          <Icon name="rotate-ccw" size={12} />
          {t?.ts ? `측정 ${fmtAgo(t.ts, now)}` : '측정값 없음'}
        </span>
      </div>

      <section className="metrics-grid" aria-label="현재 실내 측정값">
        <Metric loading={loading}
          icon="wind"
          title="이산화탄소"
          value={co2Ok ? fmtNum(co2) : '—'}
          unit="ppm"
          status={!co2Ok ? '확인 불가' : co2 >= thr ? '환기 필요' : '기준 이내'}
          tone={!co2Ok ? 'gray' : co2 >= thr ? 'amber' : 'blue'}
          note={`환기 기준 ${fmtNum(thr)} ppm`}
          series={series('co2_ppm')}
        />
        <Metric loading={loading} icon="leaf" title="초미세먼지" value={fmtNum(t?.pm25_ugm3, 1)} unit="µg/m³" status={pmIn.label} tone={pmIn.tone} note="실내 PM2.5" series={series('pm25_ugm3')} />
        <Metric loading={loading} icon="thermometer" title="온도" value={fmtNum(t?.temp_c, 1)} unit="°C" status={temp.label} tone={temp.tone} note="적정 18~26°C" series={series('temp_c')} />
        <Metric loading={loading} icon="droplets" title="습도" value={fmtNum(t?.humidity_pct)} unit="%" status={hum.label} tone={hum.tone} note="적정 40~60%" series={series('humidity_pct')} />
      </section>

      <div className="dashboard-grid">
        <RecommendationCard rec={latest?.recommendation} online={online} now={now} forecast={forecast} telemetry={t} />
        <WindowPanel
          actuator={latest?.actuator}
          online={online}
          settings={settings}
          canControl={canControl}
          recDuration={latest?.recommendation?.duration_sec}
          outdoorPm={t?.outdoor_pm25_ugm3}
          now={now}
          notify={notify}
          onChanged={refreshAll}
        />

        <section className="panel trend-panel">
          <div className="panel-head">
            <h2>CO₂ 변화와 예측</h2>
            <div className="segmented">
              {Object.keys(RANGES).map((k) => (
                <button key={k} className={range === k ? 'selected' : ''} onClick={() => setRange(k)}>
                  {k}
                </button>
              ))}
            </div>
          </div>
          <ChartLegend />
          <Co2Chart readings={spark} latestTelemetry={t} forecast={forecast} threshold={thr} rangeMs={RANGES[range]} />
          <div className="forecast-row">
            {[5, 10, 15].map((m) => {
              const p = forecast.find((f) => f.min === m)
              return (
                <div key={m}>
                  <span>{m}분 후</span>
                  <strong>
                    {p ? fmtNum(p.ppm) : '—'}
                    <small>ppm</small>
                  </strong>
                  {p && co2Ok && <Icon name={p.ppm >= co2 ? 'arrow-up-right' : 'arrow-right'} size={16} />}
                </div>
              )
            })}
          </div>
        </section>

        <OutdoorPanel telemetry={t} />
        <ActivityPanel events={events} now={now} onMore={() => go('history')} />
        <InsightPanel status={latest?.status} lastSeen={lastSeen} now={now} />
      </div>
    </>
  )
}
