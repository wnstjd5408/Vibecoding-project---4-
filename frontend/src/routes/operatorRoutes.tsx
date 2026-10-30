import type { RouteObject } from 'react-router'
import Placeholder from '../pages/Placeholder.tsx'
import { operatorPaths } from './paths.ts'
import NoteEditPage from '../operator/notes/NoteEditPage.tsx'
import NotesPage from '../operator/notes/NotesPage.tsx'

// 운영자(PC) 화면 경로 묶음. 운영자 셸(MEG-78)이 이 배열을 children으로 가진 레이아웃 경로로 감싸 같은 라우터에 붙인다(routes/index.tsx).
// 개별 운영자 화면 티켓은 이 배열에 경로를 더하고, 아직 없는 화면은 임시 빈 페이지로 둔다.
export const operatorRoutes: RouteObject[] = [
  {
    path: operatorPaths.home,
    element: <NotesPage />,
  },
  {
    path: operatorPaths.glossary,
    element: <Placeholder screenId="F5-1c" title="용어 사전" ticket="운영자 화면 티켓(MEG-78 셸 이후)" />,
  },
  {
    path: operatorPaths.reports,
    element: <Placeholder screenId="F5-2" title="신고" ticket="운영자 화면 티켓(MEG-78 셸 이후)" />,
  },
  {
    path: operatorPaths.accounts,
    element: <Placeholder screenId="F4-3a" title="계정 발급" ticket="운영자 화면 티켓(MEG-78 셸 이후)" />,
  },
  { path: operatorPaths.noteNew, element: <NoteEditPage /> },
  { path: operatorPaths.noteEdit, element: <NoteEditPage /> },
]
