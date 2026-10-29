// 공통 컴포넌트를 한 페이지에 모아 디자인(목업 v0.2)과 나란히 비교하는 개발용 화면(MEG-70). 제품 화면이 아니다.
// 토큰 → 부품 → 시트 → 화면 조립 순서다. 라이트·다크 토큰을 위쪽 버튼으로 바꿔 볼 수 있다.
import { useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import {
  AiBadge,
  AiBox,
  AppHeader,
  BottomSheet,
  Button,
  DifficultyChip,
  FavoriteToggle,
  LinkButton,
  NoteListItem,
  QuizCard,
  Scrim,
  SelectionAction,
  StateMessage,
  TermLink,
  TextField,
} from '../components/index.ts'
// 디자인 시스템 공식 목록에는 없어 index.ts에서 내보내지 않는 내부 부품
import { Badge } from '../components/Badge.tsx'
import { Chip } from '../components/Chip.tsx'
import { IconButton, IconLinkButton } from '../components/IconButton.tsx'
import { AccountIcon, ExpandIcon } from '../components/icons.tsx'
import { devPaths, noteReadPath } from '../routes/paths.ts'
import { cx } from '../components/cx.ts'
import styles from './ComponentShowcase.module.css'

const COLORS = [
  'surface-100',
  'surface-200',
  'surface-300',
  'line-strong',
  'ink',
  'ink-muted',
  'highlight',
  'pencil',
  'red-pen',
  'diff-low',
  'diff-mid',
] as const

const SUBJECTS = ['전체', '네트워크', '운영체제', '데이터베이스'] as const

// 합성 노트 목록(실제 노트가 아니다)
const NOTES = [
  { id: 11, title: '예시 노트 · 요청이 서버까지 가는 길', meta: '네트워크 · 2026-10-14' },
  { id: 12, title: '예시 노트 · 프로세스가 번갈아 실행되는 이유', meta: '운영체제 · 2026-10-09' },
  { id: 13, title: '예시 노트 · 인덱스가 조회를 빠르게 하는 방식', meta: '데이터베이스 · 2026-10-02' },
]

type SheetKind = 'dictionary' | 'ai' | null

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section} aria-label={title}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {children}
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.row}>
      <div className={styles.rowLabel}>{label}</div>
      {children}
    </div>
  )
}

export default function ComponentShowcase() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const [subject, setSubject] = useState<(typeof SUBJECTS)[number]>('전체')
  const [favoriteOn, setFavoriteOn] = useState(true)
  const [favoriteOff, setFavoriteOff] = useState(false)
  // 주소에 ?sheet=dictionary 또는 ?sheet=ai를 주면 시트가 열린 채 시작한다(F1-3처럼 열린 채 그려지는 화면 시험용)
  const [sheet, setSheet] = useState<SheetKind>(() => {
    const value = new URLSearchParams(window.location.search).get('sheet')
    return value === 'dictionary' || value === 'ai' ? value : null
  })
  const [sheetFavorite, setSheetFavorite] = useState(false)
  const [blockedClicks, setBlockedClicks] = useState(0)
  const selectionBox = useRef<HTMLDivElement>(null)
  const [selectionPos, setSelectionPos] = useState<{ top: number; left: number } | null>(null)

  // 글자를 고르면 선택 영역 바로 아래 위치를 읽어 SelectionAction에 넘긴다(본문 DOM은 감싸지 않는다).
  function handleSelect(event: ReactMouseEvent | ReactKeyboardEvent) {
    if ((event.target as HTMLElement).closest('button')) return
    const selection = window.getSelection()
    const box = selectionBox.current
    if (!selection || selection.isCollapsed || !box || !box.contains(selection.anchorNode)) {
      setSelectionPos(null)
      return
    }
    const range = selection.getRangeAt(0).getBoundingClientRect()
    const base = box.getBoundingClientRect()
    setSelectionPos({ top: range.bottom - base.top + 8, left: range.left - base.left })
  }

  return (
    <div className={styles.page} data-theme={theme}>
      <div className={styles.inner}>
        <h1 className={styles.heading}>공통 컴포넌트</h1>
        <p className={styles.lead}>
          MEG-70 · 목업 v0.2와 나란히 비교하는 개발용 화면입니다. 합성 문구만 씁니다.
        </p>
        <Button onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>
          {theme === 'light' ? '다크 토큰으로 보기' : '라이트 토큰으로 보기'}
        </Button>

        <Section title="1. 토큰">
          <Row label="색 (surface-100 위 견본)">
            <div className={styles.swatches}>
              {COLORS.map((name) => (
                <div key={name} className={styles.swatch}>
                  <span className={styles.swatchBox} style={{ background: `var(--${name})` }} />
                  {name}
                </div>
              ))}
            </div>
          </Row>
          <Row label="글자">
            <h3 className={styles.typeSample} style={{ fontSize: 24, lineHeight: '32px', fontWeight: 700 }}>
              h1 24/32 · 노트 제목
            </h3>
            <h3 className={styles.typeSample} style={{ fontSize: 20, lineHeight: '28px', fontWeight: 700 }}>
              h2 20/28 · 시트 제목
            </h3>
            <h3 className={styles.typeSample} style={{ fontSize: 17, lineHeight: '26px', fontWeight: 600 }}>
              h3 17/26 · 카드 제목
            </h3>
            <p className={styles.typeSample} style={{ fontSize: 16, lineHeight: '26px' }}>
              body 16/26 · 컨테이너는 프로세스를 격리해서 실행하는 방식이에요.
            </p>
            <p className={styles.typeSample} style={{ fontSize: 14, lineHeight: '22px' }}>
              body-sm 14/22 · 이미지가 없으면 글만 보여 줘요.
            </p>
            <p className={styles.typeSample} style={{ fontSize: 13, lineHeight: '18px', fontWeight: 500 }}>
              caption 13/18 · AI 생성
            </p>
            <pre className={styles.code}>docker run -d nginx</pre>
          </Row>
        </Section>

        <Section title="2. 버튼">
          <Row label="Button · primary / outline / report">
            <div className={styles.inline}>
              <Button variant="primary">답하기</Button>
              <Button variant="outline">로그인</Button>
              <Button variant="report">틀림 신고</Button>
            </div>
          </Row>
          <Row label="Button · 비활성">
            <div className={styles.inline}>
              <Button variant="primary" disabled>
                답하기
              </Button>
              <Button variant="outline" disabled>
                로그인
              </Button>
              <Button variant="report" disabled>
                틀림 신고
              </Button>
            </div>
          </Row>
          <Row label="Button · aria-disabled (모양과 함께 클릭도 막는다, 누르면 아래 숫자가 늘지 않아요)">
            <div className={styles.inline}>
              <Button variant="primary" aria-disabled="true" onClick={() => setBlockedClicks((n) => n + 1)}>
                답하기
              </Button>
              <span className={styles.bodySmall}>막힌 클릭이 불린 횟수: {blockedClicks}</span>
            </div>
          </Row>
          <Row label="LinkButton (다른 화면으로 가는 링크)">
            <div className={styles.inline}>
              <LinkButton to={devPaths.componentShowcase} variant="primary">
                노트 보러 가기
              </LinkButton>
            </div>
          </Row>
          <Row label="(내부용) IconButton · IconLinkButton (aria-label 필수)">
            <div className={styles.inline}>
              <IconButton label="내 계정">
                <AccountIcon />
              </IconButton>
              <IconLinkButton label="전체 보기" to={devPaths.componentShowcase}>
                <ExpandIcon />
              </IconLinkButton>
            </div>
          </Row>
          <Row label="FavoriteToggle · 켜짐 / 꺼짐">
            <div className={styles.inline}>
              <FavoriteToggle pressed={favoriteOn} onPressedChange={setFavoriteOn} />
              <FavoriteToggle pressed={favoriteOff} onPressedChange={setFavoriteOff} />
            </div>
          </Row>
        </Section>

        <Section title="3. 선택·표시">
          <Row label="(내부용) Chip · 선택 / 미선택 (눌러 보세요)">
            <div className={styles.inline}>
              {SUBJECTS.map((name) => (
                <Chip key={name} selected={subject === name} onClick={() => setSubject(name)}>
                  {name}
                </Chip>
              ))}
            </div>
          </Row>
          <Row label="AiBadge · AI 생성 / (내부용) Badge · 사전">
            <div className={styles.inline}>
              <AiBadge />
              <Badge tone="dictionary">사전</Badge>
            </div>
          </Row>
          <Row label="DifficultyChip · 하 / 중 / 상">
            <div className={styles.inline}>
              <DifficultyChip level="low" />
              <DifficultyChip level="mid" />
              <DifficultyChip level="high" />
            </div>
          </Row>
          <Row label="TermLink · 본문 속 사전 용어(<a href>, 누르면 주소는 그대로고 시트가 열린다)">
            <p className={styles.body}>
              브라우저가 주소를 입력받으면 먼저{' '}
              <TermLink href="#dns" onClick={() => setSheet('dictionary')}>
                DNS
              </TermLink>
              에 물어 서버의 위치를 찾아요.
            </p>
          </Row>
          <Row label="TermLink · 여러 줄로 나뉘는 용어(칠과 밑줄이 줄마다 이어진다)">
            <p className={cx(styles.body, styles.narrow)}>
              요청을 받으면 먼저{' '}
              <TermLink href="#resolver" onClick={() => setSheet('dictionary')}>
                도메인 이름을 숫자 주소로 바꾸는 이름 찾기 서비스
              </TermLink>
              를 거쳐요.
            </p>
          </Row>
          <Row label="SelectionAction · 아래 글자를 끌어서 골라 보세요(선택 영역 위치를 읽어 버튼 위치를 넘긴다)">
            <div ref={selectionBox} className={styles.selectionBox} onMouseUp={handleSelect} onKeyUp={handleSelect}>
              <p className={styles.body}>같은 요청이 반복되면 캐시가 이전 응답을 다시 써서 시간을 줄여요.</p>
              {selectionPos ? <SelectionAction top={selectionPos.top} left={selectionPos.left} onClick={() => setSheet('ai')} /> : null}
            </div>
          </Row>
          <Row label="AiBox · AI가 만든 내용을 감싸는 점선 상자(여백 위아래 8px, 좌우 12px)">
            <AiBox label="AI 생성 설명">
              하나의 연결을 여러 요청이 나눠 쓰는 방식이에요. 합성 문구 예시예요.
            </AiBox>
          </Row>
        </Section>

        <Section title="4. 입력 칸·퀴즈 카드·상태 안내">
          <Row label="TextField · 한 줄 / 여러 줄 / 안내 / 오류 / 비활성">
            <div style={{ display: 'grid', gap: 12 }}>
              <TextField label="이메일" type="email" placeholder="name@example.com" autoComplete="off" />
              <TextField label="내 답" multiline placeholder="답을 입력해요" />
              <TextField label="안내가 있는 칸" hint="영문 소문자와 숫자만 쓸 수 있어요." defaultValue="abc" />
              <TextField label="오류가 있는 칸" error="답을 입력해 주세요." defaultValue="" />
              <TextField label="비활성 (aria-disabled + readonly)" aria-disabled="true" defaultValue="입력할 수 없어요" />
            </div>
          </Row>
          <Row label="QuizCard (퀴즈 문항 카드)">
            <QuizCard
              badges={
                <>
                  <AiBadge />
                  <DifficultyChip level="low" />
                </>
              }
              title="HTTP와 HTTPS의 차이를 한 문장으로 말해 보세요."
              actions={
                <>
                  <Button variant="primary">답하기</Button>
                  <Button variant="report">틀림 신고</Button>
                </>
              }
            >
              <TextField label="내 답" multiline placeholder="답을 입력해요" />
            </QuizCard>
          </Row>
          <Row label="StateMessage · 빈 상태(F3-3b 문구)">
            <StateMessage
              kind="empty"
              title="오늘 풀 퀴즈가 없어요"
              description="노트에서 용어를 열어 보면 다음 날 퀴즈가 만들어져요."
              action={
                <LinkButton to={devPaths.componentShowcase} variant="primary">
                  노트 보러 가기
                </LinkButton>
              }
            />
          </Row>
          <Row label="StateMessage · 로딩 / 오류 (목업에 화면이 없어 문구는 임시)">
            <div style={{ display: 'grid', gap: 12 }}>
              <StateMessage kind="loading" title="불러오는 중이에요" description="잠시만 기다려 주세요." />
              <StateMessage
                kind="error"
                title="불러오지 못했어요"
                description="잠시 뒤 다시 시도해 주세요."
                action={<Button>다시 시도</Button>}
              />
            </div>
          </Row>
        </Section>

        <Section title="5. 앱 헤더·노트 목록 항목·스크림">
          <Row label="AppHeader · 제목형 + 로그인 버튼">
            <div className={styles.frame}>
              <AppHeader title="CS 학습 노트" actions={<Button>로그인</Button>} />
            </div>
          </Row>
          <Row label="AppHeader · 제목형 + 계정 아이콘(로그인 상태)">
            <div className={styles.frame}>
              <AppHeader
                title="CS 학습 노트"
                actions={
                  <IconButton label="내 계정">
                    <AccountIcon />
                  </IconButton>
                }
              />
            </div>
          </Row>
          <Row label="AppHeader · 뒤로 가기형 + 로그인 버튼">
            <div className={styles.frame}>
              <AppHeader backTo={devPaths.componentShowcase} actions={<Button>로그인</Button>} />
            </div>
          </Row>
          <Row label="NoteListItem">
            <div className={styles.frame}>
              {NOTES.map((note) => (
                <NoteListItem key={note.id} to={noteReadPath(note.id)} title={note.title} meta={note.meta} />
              ))}
            </div>
          </Row>
          <Row label="Scrim (뒤를 어둡게 덮는 막)">
            <div className={styles.scrimDemo}>
              <p className={styles.bodySmall}>막 아래에 있는 화면 내용이에요.</p>
              <Scrim />
            </div>
          </Row>
        </Section>

        <Section title="6. 바텀시트">
          <Row label="BottomSheet · 열고 Esc·닫기·막 누르기로 닫아 보세요(닫으면 연 버튼으로 포커스가 돌아와요)">
            <div className={styles.inline}>
              <Button onClick={() => setSheet('dictionary')}>사전 용어 시트 열기</Button>
              <Button onClick={() => setSheet('ai')}>AI 설명 시트 열기</Button>
            </div>
          </Row>
        </Section>

        <Section title="7. 화면 조립 (목업과 나란히 비교)">
          <Row label="F1-1 과목·노트 목록 조립">
            <div className={styles.frame}>
              <AppHeader title="CS 학습 노트" actions={<Button>로그인</Button>} />
              <div className={styles.frameBody}>
                <h3 className={styles.frameTitle}>과목</h3>
              </div>
              <div className={styles.chips}>
                {SUBJECTS.map((name) => (
                  <Chip key={name} selected={subject === name} onClick={() => setSubject(name)}>
                    {name}
                  </Chip>
                ))}
              </div>
              {NOTES.map((note) => (
                <NoteListItem key={note.id} to={noteReadPath(note.id)} title={note.title} meta={note.meta} />
              ))}
            </div>
          </Row>
          <Row label="F3-3a 퀴즈 문항 조립">
            <div className={styles.frame}>
              <div className={styles.frameBody}>
                <QuizCard
                  badges={
                    <>
                      <AiBadge />
                      <DifficultyChip level="mid" />
                    </>
                  }
                  title="DNS를 한 문장으로 설명해 보세요."
                  actions={
                    <>
                      <Button variant="primary">답하기</Button>
                      <Button variant="report">틀림 신고</Button>
                    </>
                  }
                >
                  <TextField label="내 답" multiline placeholder="답을 입력해요" />
                </QuizCard>
              </div>
            </div>
          </Row>
        </Section>
      </div>

      <BottomSheet
        open={sheet === 'dictionary'}
        onClose={() => setSheet(null)}
        badge={<Badge tone="dictionary">사전</Badge>}
        title={<TermLink>DNS</TermLink>}
      >
        <p className={styles.bodySmall}>
          도메인 이름을 서버의 숫자 주소로 바꿔 주는 이름 찾기 서비스예요. 합성 문구 예시예요.
        </p>
        <div className={styles.imagePlaceholder}>이미지 자리</div>
        <div className={styles.sheetActions}>
          <FavoriteToggle pressed={sheetFavorite} onPressedChange={setSheetFavorite} />
        </div>
      </BottomSheet>

      <BottomSheet
        open={sheet === 'ai'}
        onClose={() => setSheet(null)}
        badge={<AiBadge />}
        title="멀티플렉싱"
      >
        <div style={{ marginBottom: 16 }}>
          <AiBox label="AI 생성 설명">
            하나의 연결을 여러 요청이 나눠 쓰는 방식이에요. 요청마다 연결을 새로 만들지 않아서 기다리는 시간이 줄어요. 합성 문구
            예시예요.
          </AiBox>
        </div>
        <div className={styles.sheetActions}>
          <FavoriteToggle pressed={sheetFavorite} onPressedChange={setSheetFavorite} />
        </div>
      </BottomSheet>
    </div>
  )
}
