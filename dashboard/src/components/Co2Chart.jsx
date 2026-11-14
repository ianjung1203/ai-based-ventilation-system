import { Chart as ChartJS, Filler, LinearScale, LineElement, PointElement, Tooltip } from 'chart.js'
import { Line } from 'react-chartjs-2'
import { fmtHM, fmtNum, fmtTime } from '../format.js'

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Filler)
ChartJS.defaults.font.family = "'Noto Sans KR', -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif"

// 팀 UI 시안 색
const C = {
  measured: '#4b80e4',
  measuredFill: 'rgba(73,128,230,0.06)',
  predicted: '#8ba8e7',
  threshold: '#dfb67b',
  forecastBg: '#f5f8ff',
  grid: '#edf1f6',
  tick: '#6f7f98',
}

// 예측 구간 배경 (마지막 실측 ~ 끝)
const forecastShade = {
  id: 'forecastShade',
  beforeDatasetsDraw(chart, _args, opts) {
    if (!opts?.from) return
    const { ctx, chartArea, scales } = chart
    const x0 = Math.max(scales.x.getPixelForValue(opts.from), chartArea.left)
    if (x0 >= chartArea.right) return
    ctx.save()
    ctx.fillStyle = C.forecastBg
    ctx.fillRect(x0, chartArea.top, chartArea.right - x0, chartArea.bottom - chartArea.top)
    ctx.restore()
  },
}

/**
 * readings: [{ts, co2_ppm}] (오래된 순), forecast: [{t, ppm, min}], threshold: ppm, rangeMs: 보이는 기간
 */
export default function Co2Chart({ readings, latestTelemetry, forecast = [], threshold = 1000, rangeMs, height = 210 }) {
  const pts = (readings || [])
    .map((r) => ({ x: Date.parse(r.ts), y: Number(r.co2_ppm) }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
  const t = latestTelemetry
  const tx = t ? Date.parse(t.ts) : NaN
  if (Number.isFinite(tx) && Number.isFinite(Number(t.co2_ppm)) && (!pts.length || tx > pts[pts.length - 1].x)) {
    pts.push({ x: tx, y: Number(t.co2_ppm) })
  }
  pts.sort((a, b) => a.x - b.x)

  const now = Date.now()
  const last = pts[pts.length - 1]
  const fc = last ? forecast : []
  const xMin = now - rangeMs
  const xMax = Math.max(now, ...fc.map((p) => p.t)) + 30e3
  const ys = [...pts.map((p) => p.y), ...fc.map((p) => p.ppm), threshold + 200]
  const yMax = Math.ceil(Math.max(...ys) / 200) * 200

  const data = {
    datasets: [
      {
        label: '측정',
        data: pts,
        borderColor: C.measured,
        backgroundColor: C.measuredFill,
        fill: 'start',
        borderWidth: 2.4,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.25,
      },
      {
        label: 'AI 예측',
        data: fc.length ? [last, ...fc.map((p) => ({ x: p.t, y: p.ppm }))] : [],
        borderColor: C.predicted,
        backgroundColor: '#fff',
        borderWidth: 2.2,
        borderDash: [5, 5],
        pointRadius: (ctx) => (ctx.dataIndex === 0 ? 0 : 4),
        pointBorderWidth: 2,
        pointHoverRadius: 5,
      },
      {
        label: '환기 기준',
        data: [
          { x: xMin, y: threshold },
          { x: xMax, y: threshold },
        ],
        borderColor: C.threshold,
        borderWidth: 1.2,
        borderDash: [5, 5],
        pointRadius: 0,
        pointHoverRadius: 0,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    layout: { padding: { top: 4, right: 4 } },
    scales: {
      x: {
        type: 'linear',
        min: xMin,
        max: xMax,
        grid: { display: false },
        border: { display: false },
        ticks: { color: C.tick, font: { size: 12 }, maxTicksLimit: 7, callback: (v) => fmtHM(v) },
      },
      y: {
        min: 400,
        max: yMax,
        grid: { color: C.grid },
        border: { display: false },
        ticks: { color: C.tick, font: { size: 12 }, stepSize: Math.max(200, Math.ceil((yMax - 400) / 5 / 200) * 200) },
      },
    },
    plugins: {
      legend: { display: false }, // 범례는 위쪽 HTML 로 표시
      forecastShade: { from: fc.length ? last.x : null },
      tooltip: {
        backgroundColor: '#fff',
        titleColor: '#26344b',
        bodyColor: '#5d6f8a',
        borderColor: '#e2e9f2',
        borderWidth: 1,
        padding: 12,
        titleFont: { size: 13, weight: '600' },
        bodyFont: { size: 13 },
        boxPadding: 4,
        cornerRadius: 8,
        filter: (item) => item.datasetIndex !== 2 && !(item.datasetIndex === 1 && item.dataIndex === 0),
        callbacks: {
          title: (items) => (items.length ? fmtTime(items[0].parsed.x) : ''),
          label: (item) => ` ${item.dataset.label} ${fmtNum(item.parsed.y)} ppm`,
        },
      },
    },
  }

  const label = `CO2 그래프: 최근 ${pts.length}개 측정, 마지막 ${last ? fmtNum(last.y) : '-'} ppm, 환기 기준 ${fmtNum(threshold)} ppm`
  return (
    <div className="chart-wrap" style={{ height }} role="img" aria-label={label}>
      <Line data={data} options={options} plugins={[forecastShade]} />
    </div>
  )
}

export function ChartLegend({ note = '단위: ppm' }) {
  return (
    <div className="chart-legend">
      <span>
        <i className="line measured" />
        측정
      </span>
      <span>
        <i className="line predicted" />
        AI 예측
      </span>
      <span>
        <i className="line threshold" />
        환기 기준
      </span>
      <small>{note}</small>
    </div>
  )
}
