// API 호출 모음. 주소는 .env 의 VITE_API_URL (깃에 올리지 않음)
export const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
export const DEVICE_ID = import.meta.env.VITE_DEVICE_ID || 'vent-01'

async function request(method, path, body) {
  if (!API_URL) throw new Error('VITE_API_URL 이 비어 있어요 (dashboard/.env 확인)')
  const res = await fetch(API_URL + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    const msg = (data && (data.message || data.error)) || `HTTP ${res.status}`
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return data
}

const dev = (p = '') => `/devices/${encodeURIComponent(DEVICE_ID)}${p}`

export const getLatest = () => request('GET', dev('/latest'))

// type: readings | predictions | recommendations | actuator | occupancy
// 최대 7일·1,000건/페이지 -> next_token 으로 이어 받기 (최대 maxPages)
export async function getHistory(type, fromIso, toIso, maxPages = 10) {
  const items = []
  let token = null
  for (let i = 0; i < maxPages; i++) {
    const q = new URLSearchParams({ type, from: fromIso, to: toIso, limit: '1000' })
    if (token) q.set('next_token', token)
    const page = await request('GET', dev(`/history?${q}`))
    items.push(...(page.items || []))
    token = page.next_token
    if (!token) break
  }
  return items
}

export const getSettings = () => request('GET', dev('/settings'))
export const putSettings = (body) => request('PUT', dev('/settings'), body)
export const putScenario = (body) => request('PUT', dev('/scenario'), body)
export const putOccupancy = (value) => request('PUT', dev('/occupancy'), { occupancy_set: value })
export const putRun = (action, note) => request('PUT', dev('/run'), { action, note })
export const postActuator = (action, durationSec) =>
  request('POST', dev('/actuator'), action === 'OPEN' ? { action, duration_sec: durationSec } : { action })
export const getCommand = (cmdId) => request('GET', `/commands/${encodeURIComponent(cmdId)}`)
