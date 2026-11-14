import { createElement } from 'react'
import ICONS from './icons.json'

// 팀 UI 시안과 같은 선 아이콘 (lucide)
export default function Icon({ name, size = 18, className }) {
  const shapes = ICONS[name] || ICONS.wind
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {shapes.map(([tag, attrs], i) => createElement(tag, { key: i, ...attrs }))}
    </svg>
  )
}
