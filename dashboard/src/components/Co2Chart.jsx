import { useCallback, useEffect, useMemo, useState } from 'react'
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from 'chart.js'
import { Line } from 'react-chartjs-2'
import { getHistory } from '../api.js'
import { fmtHM, fmtNum, fmtTime, predictionPoints } from '../format.js'

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend)

const RANGES = [
  { key: '1h', label: '1시간', ms: 3600e3, refreshMs: 15000 },
  { key: '6h', label: '6시간', ms: 6 * 3600e3, refreshMs: 60000 },
  { key: '24h', label: '24시간', ms: 24 * 3600e3, refreshMs: 60000 },
]

// CSS 변수(라이트/다크)에서 색을 읽어 차트에 넘긴다
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export default function Co2Chart({ latest, settings }) {
  const [range, setRange] = useState(RANGES[0])
  const [readings, setReadings] = useState([])
  const [error, setError] = useState(null)
  const [showTable, setShowTable] = useState(false)

  const load = useCallback(async () => {
    if (document.hidden) return
    const to = new Date()
    const from = new Date(to.getTime() - range.ms)
    try {
      const items = await getHistory('readings', from.toISOString(), to.toISOString())
      setReadings(items)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [range])

  useEffect(() => {
    load()
    const t = setInterval(load, range.refreshMs)
    return () => clearInterval(t)
  }, [load, range])

  // 5초마다 오는 /latest 의 telemetry 를 그래프 끝에 이어 붙여 '지금' 을 바로 보여 준다
  const points = useMemo(() => {
    const pts = readings
      .map((r) => ({ x: Date.parse(r.ts), y: Number(r.co2_ppm) }))
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
    const t = latest?.telemetry
    const tx = t ? Date.parse(t.ts) : NaN
    if (Number.isFinite(tx) && Number.isFinite(Number(t.co2_ppm)) && (!pts.length || tx > pts[pts.length - 1].x)) {
      pts.push({ x: tx, y: Number(t.co2_ppm) })
    }
    return pts.sort((a, b) => a.x - b.x)
  }, [readings, latest])

  const pred = useMemo(() => predictionPoints(latest?.prediction), [latest])
  const threshold = Number(settings?.effective?.co2_threshold_ppm ?? 1000)

  const now = Date.now()
  const xMin = now - range.ms
  const lastPred = pred.length ? pred[pred.length - 1].t : now
  const xMax = Math.max(now, lastPred) + 60e3

  const colors = {
    series: cssVar('--series-1') || '#2a78d6',
    ref: cssVar('--text-secondary') || '#52514e',
    grid: cssVar('--grid') || '#e1e0d9',
    text: cssVar('--text-secondary') || '#52514e',
    surface: cssVar('--surface-1') || '#fcfcfb',
  }

  const predLine = pred.length && points.length ? [points[points.length - 1], ...pred.map((p) => ({ x: p.t, y: p.ppm }))] : []

  const data = {
    datasets: [
      {
        label: '실측 CO2',
        data: points,
        borderColor: colors.series,
        backgroundColor: colors.series,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.2,
      },
      {
        label: '예측 (+5/+10/+15분)',
        data: predLine,
        borderColor: colors.series,
        backgroundColor: colors.surface,
        borderWidth: 2,
        borderDash: [6, 4],
        pointRadius: (ctx) => (ctx.dataIndex === 0 ? 0 : 4),
        pointBorderWidth: 2,
        pointHoverRadius: 5,
      },
      {
        label: `환기 기준 ${fmtNum(threshold)} ppm`,
        data: [
          { x: xMin, y: threshold },
          { x: xMax, y: threshold },
        ],
        borderColor: colors.ref,
        borderWidth: 1,
        borderDash: [2, 4],
        pointRadius: 0,
        pointHoverRadius: 0,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    parsing: true,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    scales: {
      x: {
        type: 'linear',
        min: xMin,
        max: xMax,
        grid: { color: colors.grid },
        ticks: { color: colors.text, maxTicksLimit: 7, callback: (v) => fmtHM(v) },
      },
      y: {
        suggestedMin: 400,
        suggestedMax: Math.max(threshold + 200, 1200),
        grid: { color: colors.grid },
        ticks: { color: colors.text },
        title: { display: true, text: 'ppm', color: colors.text },
      },
    },
    plugins: {
      legend: { position: 'top', align: 'start', labels: { color: colors.text, boxWidth: 18, usePointStyle: false } },
      tooltip: {
        filter: (item) => item.datasetIndex !== 2,
        callbacks: {
          title: (items) => (items.length ? fmtTime(items[0].parsed.x) : ''),
          label: (item) => `${item.dataset.label}: ${fmtNum(item.parsed.y)} ppm`,
        },
      },
    },
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>CO2 변화와 예측</h2>
        <div className="seg" role="group" aria-label="기간">
          {RANGES.map((r) => (
            <button key={r.key} className={r.key === range.key ? 'on' : ''} onClick={() => setRange(r)}>
              {r.label}
            </button>
          ))}
          <button className={showTable ? 'on' : ''} onClick={() => setShowTable((s) => !s)}>
            표로 보기
          </button>
        </div>
      </div>
      {error && <div className="banner serious">그래프 데이터를 못 받았어요: {error}</div>}
      {!pred.length && <p className="sub">예측 데이터가 아직 없어요 (파이가 prediction 을 보내면 점선으로 표시돼요).</p>}
      <div className="chart-box">
        <Line data={data} options={options} />
      </div>
      {showTable && <ReadingsTable readings={readings} pred={pred} />}
    </section>
  )
}

function ReadingsTable({ readings, pred }) {
  const rows = readings.slice(-20).reverse()
  return (
    <div className="table-wrap">
      {pred.length > 0 && (
        <p className="sub">
          예측: {pred.map((p) => `+${p.min}분 ${fmtNum(p.ppm)}ppm`).join(' · ')}
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>시각</th>
            <th>CO2 (ppm)</th>
            <th>PM2.5</th>
            <th>온도</th>
            <th>습도</th>
            <th>인원</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.sk || r.ts}>
              <td>{fmtTime(r.ts)}</td>
              <td>{fmtNum(r.co2_ppm)}</td>
              <td>{fmtNum(r.pm25_ugm3, 1)}</td>
              <td>{fmtNum(r.temp_c, 1)}</td>
              <td>{fmtNum(r.humidity_pct)}</td>
              <td>{fmtNum(r.occupancy)}</td>
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={6} className="sub">
                이 기간에 측정값이 없어요.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
