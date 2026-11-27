import { lazy } from 'react'

// 가이드 미리보기(개발 전용)는 본 번들에 넣지 않고 /dev/guide에 들어갈 때만 불러온다.
export const GuidePreview = lazy(() => import('./GuidePreviewPage.tsx'))
