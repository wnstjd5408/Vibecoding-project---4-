import type { RouteObject } from 'react-router'
import LoginPage from '../pages/LoginPage.tsx'
import MyInfoPage from '../pages/MyInfoPage.tsx'
import Placeholder from '../pages/Placeholder.tsx'
import { userPaths } from './paths.ts'

// 사용자(모바일) 화면 경로 묶음. 아직 없는 화면은 임시 빈 페이지로 연결해 두고, 해당 티켓이 그 줄의 element를 교체한다.
export const userRoutes: RouteObject[] = [
  { path: userPaths.noteList, element: <Placeholder screenId="F1-1" title="과목·노트 목록" ticket="MEG-72" withHeader /> },
  { path: userPaths.noteRead, element: <Placeholder screenId="F1-2" title="노트 읽기" ticket="MEG-74" withHeader /> },
  // TODO(MEG-108): 퀴즈 첫 화면(F3-3a)은 MEG-108에서 만든다. 그때 이 임시 빈 페이지를 교체한다.
  { path: userPaths.quiz, element: <Placeholder screenId="F3-3a" title="오늘의 퀴즈" ticket="MEG-108" withHeader /> },
  { path: userPaths.login, element: <LoginPage /> },
  { path: userPaths.myInfo, element: <MyInfoPage /> },
]
