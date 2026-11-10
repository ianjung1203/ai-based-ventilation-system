import { fmtAgo, fmtDateTime, fmtDuration, REASON_TEXT, RESULT_TEXT, STATE_TEXT, TRIGGER_TEXT } from '../format.js'

export default function StatusCards({ recommendation: r, actuator: a, now }) {
  return (
    <section className="card">
      <h2>환기 추천</h2>
      {r ? (
        <dl className="kv">
          <dt>판단</dt>
          <dd>
            <b>{r.need_vent ? '환기 필요' : '환기 불필요'}</b>
          </dd>
          <dt>시작</dt>
          <dd>{fmtDateTime(r.start_ts)}</dd>
          <dt>권장 시간</dt>
          <dd>{fmtDuration(r.duration_sec)}</dd>
          <dt>사유</dt>
          <dd>
            {REASON_TEXT[r.reason_code] || r.reason_code} <span className="sub">({r.reason_code})</span>
          </dd>
          <dt>받은 시각</dt>
          <dd className="sub">{fmtAgo(r.ts, now)}</dd>
        </dl>
      ) : (
        <p className="sub">아직 추천이 없어요.</p>
      )}

      <h2 className="mt">환기 모터</h2>
      {a ? (
        <dl className="kv">
          <dt>상태</dt>
          <dd>
            <b>{STATE_TEXT[a.state] || a.state}</b>
          </dd>
          <dt>원인</dt>
          <dd>{TRIGGER_TEXT[a.trigger] || a.trigger}</dd>
          <dt>결과</dt>
          <dd>{RESULT_TEXT[a.result] || a.result}</dd>
          <dt>시각</dt>
          <dd className="sub">
            {fmtDateTime(a.ts)} ({fmtAgo(a.ts, now)})
          </dd>
        </dl>
      ) : (
        <p className="sub">모터 기록이 없어요.</p>
      )}
    </section>
  )
}
