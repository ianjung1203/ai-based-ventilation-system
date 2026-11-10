import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' : S3 + CloudFront 에 올릴 때 경로가 깨지지 않게
export default defineConfig({
  plugins: [react()],
  base: './',
})
