// 시간은 서버·DB 에서는 UTC, 화면에서만 KST 로 바꾼다.
const kstTime = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})
const kstShort = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false,
})
const kstDateTime = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
})

const toDate = (v) => (v instanceof Date ? v : new Date(typeof v === 'number' ? v : Date.parse(v)))
const valid = (d) => d instanceof Date && !Number.isNaN(d.getTime())

export function fmtTime(v) {
  const d = toDate(v)
  return valid(d) ? kstTime.format(d) : '-'
}
export function fmtHM(v) {
  const d = toDate(v)
  return valid(d) ? kstShort.format(d) : '-'
}
export function fmtDateTime(v) {
  const d = toDate(v)
  return valid(d) ? kstDateTime.format(d) : '-'
}

// "3분 전", "15초 전"
export function fmtAgo(v, now = Date.now()) {
  const d = toDate(v)
  if (!valid(d)) return '-'
  const s = Math.round((now - d.getTime()) / 1000)
  if (s < 0) return `${-s}초 뒤`
  if (s < 60) return `${s}초 전`
  if (s < 3600) return `${Math.floor(s / 60)}분 전`
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`
  return `${Math.floor(s / 86400)}일 전`
}

export function fmtDuration(sec) {
  const n = Number(sec)
  if (!Number.isFinite(n)) return '-'
  const m = Math.floor(n / 60)
  const s = Math.round(n % 60)
  if (m === 0) return `${s}초`
  return s ? `${m}분 ${s}초` : `${m}분`
}

export function fmtNum(v, digits = 0) {
  const n = Number(v)
  if (v === null || v === undefined || !Number.isFinite(n)) return '-'
  return n.toLocaleString('ko-KR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

// SAD 4.2 reason_code
export const REASON_TEXT = {
  CO2_HIGH: 'CO2 농도가 높아요',
  PM_BAD_SPLIT: '바깥 미세먼지가 나빠서 짧게 나눠 환기해요',
  PM_VERY_BAD_HOLD: '바깥 미세먼지가 매우 나빠서 환기를 미뤄요',
  CO2_OVERRIDE: 'CO2가 매우 높아서 미세먼지와 상관없이 환기해요',
  UNREACHABLE: '목표 농도까지 낮추기 어려워요',
  PROTECT_OPEN: '보호 동작으로 열어요',
}

export const RESULT_TEXT = {
  OK: '성공',
  EXPIRED: '시간 초과로 무시됨 (30초 지난 명령)',
  DUPLICATE: '이미 처리한 명령',
  BLOCKED: '안전 규칙으로 거부됨',
}

export const STATE_TEXT = { OPEN: '열림', CLOSED: '닫힘', ERROR: '오류' }
export const TRIGGER_TEXT = { AUTO: '자동', MANUAL: '수동', SAFETY: '안전' }

// 예측 메시지에서 +5/+10/+15분 CO2 를 꺼낸다.
// 파이 담당이 정한 필드 이름을 아직 몰라서 흔한 모양을 모두 받아 준다.
//   { co2_pred_ppm: [..], horizons_min: [5,10,15] }
//   { predictions: [{ horizon_min: 5, co2_ppm: .. }, ..] }
//   { co2_5m_ppm: .., co2_10m_ppm: .., co2_15m_ppm: .. }  (co2 와 5/10/15 가 들어간 키)
const HORIZONS = [5, 10, 15]
export function predictionPoints(pred) {
  if (!pred) return []
  const base = Date.parse(pred.ts)
  if (!Number.isFinite(base)) return []
  const arr = pred.co2_pred_ppm ?? pred.pred_co2_ppm ?? pred.co2_ppm_pred ?? pred.predictions
  if (Array.isArray(arr)) {
    const hz = Array.isArray(pred.horizons_min) ? pred.horizons_min : HORIZONS
    return arr
      .map((v, i) => {
        const min = Number(typeof v === 'object' && v ? v.horizon_min ?? hz[i] : hz[i])
        const ppm = Number(typeof v === 'object' && v ? v.co2_ppm ?? v.ppm ?? v.value : v)
        return { min, ppm, t: base + min * 60000 }
      })
      .filter((p) => Number.isFinite(p.ppm) && Number.isFinite(p.min))
  }
  const out = []
  for (const h of HORIZONS) {
    const re = new RegExp(`(^|[^0-9])${h}([^0-9]|$)`)
    const key = Object.keys(pred).find((k) => /co2/i.test(k) && re.test(k))
    const ppm = key ? Number(pred[key]) : NaN
    if (Number.isFinite(ppm)) out.push({ min: h, ppm, t: base + h * 60000 })
  }
  return out
}
