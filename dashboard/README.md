# vent-dashboard (C2 정훈)

React + Chart.js 대시보드. 5초마다 `/latest`, 그래프는 `/history`.

## 실행 (노트북)
```
cd dashboard
copy .env.example .env      (VITE_API_URL 채우기)
npm install
npm run dev                 -> http://localhost:5173
```

## 화면
- 상태(온라인/오프라인), CO2·PM2.5·온습도·인원, 바깥 공기
- CO2 그래프(실측 + 예측 +5/+10/+15분 + 기준선), 표로 보기
- 환기 추천, 모터 상태
- 수동 환기: 확인 중 -> 결과 / 30초 뒤 응답 없음 (SAD 4.2)
- 설정·시나리오·인원·실험 시작/종료 (Shadow desired)
- 시간은 화면에서만 KST

## 주의
- 로그인(Cognito) 전까지 API 주소와 화면 주소를 공개하지 않는다.
- 빌드하면 VITE_API_URL 이 JS 안에 들어간다 -> 배포(S3+CloudFront)는 Cognito 이후.
