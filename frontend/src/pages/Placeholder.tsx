import DevNav from './DevNav.tsx'

// 아직 없는 화면을 잠시 대신하는 빈 페이지. 해당 티켓이 화면을 만들 때 이 페이지를 교체한다.
export default function Placeholder({ screenId, title, ticket }: { screenId: string; title: string; ticket: string }) {
  return (
    <main style={{ padding: '2rem' }}>
      <h1>
        {screenId} {title}
      </h1>
      <p>
        임시 빈 페이지입니다. 이 화면은 {ticket}에서 만듭니다.
      </p>
      <DevNav />
    </main>
  )
}
