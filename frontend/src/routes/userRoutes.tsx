import type { RouteObject } from 'react-router'
import LoginPage from '../pages/LoginPage.tsx'
import NoteListPage from '../pages/NoteListPage.tsx'
import NoteReadPage from '../pages/NoteReadPage.tsx'
import MyInfoPage from '../pages/MyInfoPage.tsx'
import QuizPage from '../pages/QuizPage.tsx'
import { userPaths } from './paths.ts'

// 사용자(모바일) 화면 경로 묶음. 아직 없는 화면이 생기면 임시 빈 페이지(Placeholder)로 연결해 두고, 해당 티켓이 그 줄의 element를 교체한다.
export const userRoutes: RouteObject[] = [
  { path: userPaths.noteList, element: <NoteListPage /> },
  { path: userPaths.noteRead, element: <NoteReadPage /> },
  { path: userPaths.quiz, element: <QuizPage /> },
  { path: userPaths.login, element: <LoginPage /> },
  { path: userPaths.myInfo, element: <MyInfoPage /> },
]
