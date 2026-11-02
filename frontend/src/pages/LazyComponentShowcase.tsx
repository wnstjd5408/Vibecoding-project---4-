import { lazy } from 'react'

// 개발용 쇼케이스는 본 번들에 넣지 않고 /dev/components에 들어갈 때만 불러온다.
export const ComponentShowcase = lazy(() => import('./ComponentShowcase.tsx'))
