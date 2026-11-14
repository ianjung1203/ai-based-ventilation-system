# vent-dashboard (C2 정훈) · UI v1.1

팀 UI 시안(열어조 · AI 환기 대시보드) 디자인 + 실제 API 데이터.

## 실행
```
cd dashboard
copy .env.example .env      (VITE_API_URL 채우기, 처음 한 번)
npm install                 (처음 한 번)
npm run dev                 -> http://localhost:5173
```

## 화면 (주소 뒤 #으로 이동)
- #dashboard  : 실험 배너(누르면 실험 화면), 측정 카드 4개 + 추세선, AI 환기 추천, 환기 창문(열기/닫기·자동 환기),
                CO2 그래프(측정·예측·기준선) + 5/10/15분 예측, 창밖의 공기, 최근 기록, 장치 상태
- #history    : 센서 측정 그래프·표 / 환기·추천 기록, 1·6·24시간, CSV 내보내기
- #experiment : 실험 회차 시작·종료(run_id), 인원 고정, 바깥 공기 시나리오(프리셋 6개 + 직접 입력)
- #settings   : 환기 기준(Shadow desired) 저장, 파이 보고값, 장치 정보, 보호 규칙

## 데이터
- 5초마다 /latest, 15초마다 최근 1시간 readings, 30초마다 설정·기록
- 온라인/마지막 연결: status.online, last_seen_ts (서버 수신 시각 기준 15분)
- 수동 명령: 확인 중 -> 결과 / 30초 뒤 응답 없음 (SAD 4.2)
- 시간은 화면에서만 KST

## 주의
- 로그인(Cognito) 전까지 API 주소와 화면 주소를 공개하지 않는다.
- 빌드하면 VITE_API_URL 이 JS 안에 들어간다 -> 배포(S3+CloudFront)는 Cognito 이후.
