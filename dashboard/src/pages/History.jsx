import { useCallback, useEffect, useState } from 'react'
import Icon from '../Icon.jsx'
import { Badge } from '../ui.jsx'
import { getHistory } from '../api.js'
import { buildEvents, fmtNum, fmtTime } from '../format.js'
import Co2Chart, { ChartLegend } from '../components/Co2Chart.jsx'
import { EventItem } from '../components/Panels.jsx'

const RANGES = { '1시간': 3600e3, '6시간': 6 * 3600e3, '24시간': 24 * 3600e3 }
const TABLE_MAX = 200

export default function History({ settings, now, latest }) {
  const [tab, setTab] = useState('readings')
  const [range, setRange] = useState('1시간')
  const [rows, setRows] = useState([])
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    const to = new Date()
    const from = new Date(to.getTime() - RANGES[range])
    setLoading(true)
    try {
      const [r, a, c] = await Promise.all([
        getHistory('readings', from.toISOString(), to.toISOString()),
        getHistory('actuator', from.toISOString(), to.toISOString(), 3),
        getHistory('recommendations', from.toISOString(), to.toISOString(), 3),
      ])
      setRows(r)
      setEvents(buildEvents(a, c))
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => {
    load()
    const t = setInterval(load, range === '1시간' ? 30000 : 60000)
    return () => clearInterval(t)
  }, [load, range])

  const thr = Number(settings?.effective?.co2_threshold_ppm ?? 1000)

  function exportCsv() {
    const data =
      tab === 'readings'
        ? [
            ['timestamp_kst', 'co2_ppm', 'pm25_ugm3', 'temp_c', 'humidity_pct', 'occupancy', 'outdoor_pm25_ugm3', 'outdoor_temp_c', 'run_id'],
            ...rows.map((r) => [
              new Date(r.ts).toLocaleString('sv-SE', { timeZone: 'Asia/Seoul' }),
              r.co2_ppm, r.pm25_ugm3, r.temp_c, r.humidity_pct, r.occupancy, r.outdoor_pm25_ugm3, r.outdoor_temp_c, r.run_id,
            ]),
          ]
        : [['timestamp_kst', 'title', 'detail'], ...events.map((e) => [new Date(e.ts).toLocaleString('sv-SE', { timeZone: 'Asia/Seoul' }), e.title, e.detail])]
    const csv = '﻿' + data.map((r) => r.map((v) => `"${String(v ?? '').replaceAll('"', '""')}"`).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `vent-${tab}-${range}.csv`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const shown = rows.slice(-TABLE_MAX).reverse()

  return (
    <section className="panel history-panel">
      <div className="panel-head">
        <h2>실험 데이터</h2>
        <button className="button secondary compact" onClick={exportCsv} disabled={tab === 'readings' ? !rows.length : !events.length}>
          <Icon name="download" size={16} />
          CSV 내보내기
        </button>
      </div>
      <div className="history-toolbar">
        <div className="tabs">
          <button className={tab === 'readings' ? 'active' : ''} onClick={() => setTab('readings')}>
            센서 측정 <span>{rows.length}</span>
          </button>
          <button className={tab === 'events' ? 'active' : ''} onClick={() => setTab('events')}>
            환기·추천 기록 <span>{events.length}</span>
          </button>
        </div>
        <select aria-label="조회 기간" value={range} onChange={(e) => setRange(e.target.value)}>
          {Object.keys(RANGES).map((k) => (
            <option key={k} value={k}>
              최근 {k}
            </option>
          ))}
        </select>
      </div>
      {error && <p className="form-error">기록을 받지 못했어요: {error}</p>}

      {tab === 'readings' ? (
        <>
          <div className="history-chart">
            <ChartLegend note={loading ? '불러오는 중…' : '단위: ppm'} />
            <Co2Chart readings={rows} latestTelemetry={latest?.telemetry} threshold={thr} rangeMs={RANGES[range]} height={250} />
          </div>
          <div className="table-scroll">
            <table>
              <caption>
                {rows.length}건 중 최근 {shown.length}건 · 시간은 KST
              </caption>
              <thead>
                <tr>
                  <th>측정 시각</th>
                  <th>CO₂ (ppm)</th>
                  <th>PM2.5 (µg/m³)</th>
                  <th>온도 (°C)</th>
                  <th>습도 (%)</th>
                  <th>인원</th>
                  <th>바깥 PM2.5</th>
                  <th>실험</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.sk || r.ts}>
                    <td>{fmtTime(r.ts)}</td>
                    <td className={Number(r.co2_ppm) >= thr ? 'value-warning' : 'value-blue'}>{fmtNum(r.co2_ppm)}</td>
                    <td>{fmtNum(r.pm25_ugm3, 1)}</td>
                    <td>{fmtNum(r.temp_c, 1)}</td>
                    <td>{fmtNum(r.humidity_pct)}</td>
                    <td>{fmtNum(r.occupancy)}</td>
                    <td>{fmtNum(r.outdoor_pm25_ugm3, 1)}</td>
                    <td>{r.run_id && r.run_id !== 'NONE' ? <Badge tone="green">{r.run_id}</Badge> : <span className="muted">-</span>}</td>
                  </tr>
                ))}
                {!shown.length && (
                  <tr>
                    <td colSpan={8} className="muted">
                      {loading ? '불러오는 중…' : '이 기간에 측정값이 없어요.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="event-timeline">
          {events.map((ev) => (
            <EventItem key={ev.key} ev={ev} now={now} />
          ))}
          {!events.length && <p className="empty-state">{loading ? '불러오는 중…' : '이 기간에 기록이 없어요.'}</p>}
        </div>
      )}
    </section>
  )
}
