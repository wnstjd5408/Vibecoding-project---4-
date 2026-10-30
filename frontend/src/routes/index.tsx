import type { RouteObject } from 'react-router'
import { Suspense } from 'react'
import { ComponentShowcase } from '../pages/LazyComponentShowcase.tsx'
import FoundationDemo from '../pages/FoundationDemo.tsx'
import Placeholder from '../pages/Placeholder.tsx'
import { operatorRoutes } from './operatorRoutes.tsx'
import { devPaths } from './paths.ts'
import { userRoutes } from './userRoutes.tsx'
import { MockupLayout, MockupCatalog, MockupScreen } from '../mockup/LazyMockup.tsx'

// 앱의 모든 경로. 사용자(모바일) 묶음과 운영자(PC) 묶음이 같은 라우터 하나에 붙는다.
export const appRoutes: RouteObject[] = [
  ...userRoutes,
  ...operatorRoutes,
  { path: devPaths.foundationDemo, element: <FoundationDemo /> },
  { path: devPaths.mockup, element: <Suspense fallback={<p role="status">화면을 불러오는 중…</p>}><MockupLayout /></Suspense>, children: [
    { index: true, element: <MockupCatalog /> },
    { path: ':screenId', element: <MockupScreen /> },
  ] },
  { path: devPaths.componentShowcase, element: <Suspense fallback={<p role="status">화면을 불러오는 중…</p>}><ComponentShowcase /></Suspense> },
  { path: '*', element: <Placeholder screenId="404" title="없는 경로" ticket="해당 없음" /> },
]
