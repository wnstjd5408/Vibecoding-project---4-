import { Route, Routes } from 'react-router'
import FoundationDemo from './pages/FoundationDemo.tsx'
import Placeholder from './pages/Placeholder.tsx'
import { paths } from './routes.ts'

// 화면 경로 표. 아직 없는 화면은 임시 빈 페이지로 연결해 두고, 해당 티켓이 이 줄의 element를 교체한다.
function App() {
  return (
    <Routes>
      <Route path={paths.noteList} element={<Placeholder screenId="F1-1" title="과목·노트 목록" ticket="MEG-72" />} />
      <Route path={paths.noteRead} element={<Placeholder screenId="F1-2" title="노트 읽기" ticket="MEG-74" />} />
      {/* TODO(MEG-91): 퀴즈 첫 화면(F3-3a)은 MEG-91에서 만든다. 그때 이 임시 빈 페이지를 교체한다. */}
      <Route path={paths.quiz} element={<Placeholder screenId="F3-3a" title="오늘의 퀴즈" ticket="MEG-91" />} />
      <Route path={paths.login} element={<Placeholder screenId="F4-1" title="로그인" ticket="MEG-64" />} />
      <Route path={paths.myInfo} element={<Placeholder screenId="F4-5" title="내 정보" ticket="MEG-65" />} />
      <Route path={paths.foundationDemo} element={<FoundationDemo />} />
      <Route path="*" element={<Placeholder screenId="404" title="없는 경로" ticket="해당 없음" />} />
    </Routes>
  )
}

export default App
