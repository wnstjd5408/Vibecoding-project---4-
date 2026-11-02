// 목업 v0.2에서 쓴 아이콘. 글자 라벨은 버튼의 aria-label이 맡으므로 아이콘 자체는 스크린 리더에서 숨긴다.
const common = {
  width: 22,
  height: 22,
  viewBox: '0 0 24 24',
  stroke: 'currentColor',
  strokeWidth: 2,
  'aria-hidden': true,
} as const

// 계정(사람)
export function AccountIcon() {
  return (
    <svg {...common} fill="none" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
    </svg>
  )
}

// 즐겨찾기(별). filled가 true면 채워서 켜진 상태를 보여 준다.
export function StarIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg {...common} fill={filled ? 'currentColor' : 'none'} strokeLinejoin="round">
      <path d="M12 3.5l2.6 5.3 5.9.9-4.25 4.15 1 5.85L12 16.9l-5.25 2.8 1-5.85L3.5 9.7l5.9-.9L12 3.5z" />
    </svg>
  )
}

// 전체 보기(바깥으로 펼침)
export function ExpandIcon() {
  return (
    <svg {...common} fill="none" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
    </svg>
  )
}
