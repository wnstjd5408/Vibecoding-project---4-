import { Link } from 'react-router'
import { devPaths, noteReadPath, operatorPaths, userPaths } from '../routes/paths.ts'

type NavLink = { to: string; label: string }

const userLinks: NavLink[] = [
  { to: userPaths.noteList, label: 'F1-1 과목·노트 목록' },
  { to: noteReadPath(11), label: 'F1-2 노트 읽기(노트 11)' },
  { to: userPaths.quiz, label: 'F3-3a 오늘의 퀴즈' },
  { to: userPaths.login, label: 'F4-1 로그인' },
  { to: userPaths.myInfo, label: 'F4-5 내 정보' },
]

const operatorLinks: NavLink[] = [{ to: operatorPaths.home, label: 'F5-1a 운영자 노트 목록' }]

const devLinks: NavLink[] = [{ to: devPaths.foundationDemo, label: '공통 기반 샘플' }]

function LinkGroup({ title, links }: { title: string; links: NavLink[] }) {
  return (
    <section aria-label={title}>
      <h2>{title}</h2>
      <ul>
        {links.map((link) => (
          <li key={link.to}>
            <Link to={link.to}>{link.label}</Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

// 공통 기반 확인용 이동 링크. 화면 티켓이 실제 헤더·이동 구성을 만들면 쓰지 않는다.
// 사용자(모바일) 묶음과 운영자(PC) 묶음이 같은 라우터에 붙어 서로 이동할 수 있음을 보여 준다.
export default function DevNav() {
  return (
    <nav aria-label="화면 이동">
      <LinkGroup title="사용자(모바일) 화면" links={userLinks} />
      <LinkGroup title="운영자(PC) 화면" links={operatorLinks} />
      <LinkGroup title="개발용" links={devLinks} />
    </nav>
  )
}
