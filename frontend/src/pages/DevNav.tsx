import { Link } from 'react-router'
import { noteReadPath, paths } from '../routes.ts'

// 공통 기반 확인용 이동 링크. 화면 티켓이 실제 헤더·이동 구성을 만들면 쓰지 않는다.
export default function DevNav() {
  const links: { to: string; label: string }[] = [
    { to: paths.noteList, label: 'F1-1 과목·노트 목록' },
    { to: noteReadPath(11), label: 'F1-2 노트 읽기(노트 11)' },
    { to: paths.quiz, label: 'F3-3a 오늘의 퀴즈' },
    { to: paths.login, label: 'F4-1 로그인' },
    { to: paths.myInfo, label: 'F4-5 내 정보' },
    { to: paths.foundationDemo, label: '공통 기반 샘플' },
  ]
  return (
    <nav aria-label="화면 이동">
      <ul>
        {links.map((link) => (
          <li key={link.to}>
            <Link to={link.to}>{link.label}</Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}
