// 공통 컴포넌트를 한 페이지에 모아 디자인(목업 v0.2)과 나란히 비교하는 개발용 화면(MEG-70). 제품 화면이 아니다.
// 토큰 → 부품 → 시트 → 화면 조립 순서다. 라이트·다크 토큰을 위쪽 버튼으로 바꿔 볼 수 있다.
import { useState } from 'react'
import type { ReactNode } from 'react'
import {
  AccountIcon,
  AiBox,
  AppHeader,
  Badge,
  BottomSheet,
  Button,
  Card,
  Chip,
  DifficultyChip,
  ExpandIcon,
  FavoriteToggle,
  Field,
  GlossaryTerm,
  IconButton,
  IconLinkButton,
  LinkButton,
  NoteListItem,
  Scrim,
} from '../components/index.ts'
import { devPaths, noteReadPath } from '../routes/paths.ts'
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
  const [sheet, setSheet] = useState<SheetKind>(null)
  const [sheetFavorite, setSheetFavorite] = useState(false)

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
              <Button variant="report">오류 신고</Button>
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
                오류 신고
              </Button>
            </div>
          </Row>
          <Row label="LinkButton (다른 화면으로 가는 링크)">
            <div className={styles.inline}>
              <LinkButton to={devPaths.componentShowcase} variant="primary">
                노트 보러 가기
              </LinkButton>
            </div>
          </Row>
          <Row label="IconButton · IconLinkButton (aria-label 필수)">
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
          <Row label="Chip · 선택 / 미선택 (눌러 보세요)">
            <div className={styles.inline}>
              {SUBJECTS.map((name) => (
                <Chip key={name} selected={subject === name} onClick={() => setSubject(name)}>
                  {name}
                </Chip>
              ))}
            </div>
          </Row>
          <Row label="Badge · 사전 / AI 생성">
            <div className={styles.inline}>
              <Badge tone="dictionary">사전</Badge>
              <Badge tone="ai">AI 생성</Badge>
            </div>
          </Row>
          <Row label="DifficultyChip · 하 / 중 / 상">
            <div className={styles.inline}>
              <DifficultyChip level="low" />
              <DifficultyChip level="mid" />
              <DifficultyChip level="high" />
            </div>
          </Row>
          <Row label="GlossaryTerm · 본문 속 사전 용어(누르면 시트가 열린다)">
            <p className={styles.body}>
              브라우저가 주소를 입력받으면 먼저 <GlossaryTerm onClick={() => setSheet('dictionary')}>DNS</GlossaryTerm>에 물어 서버의
              위치를 찾아요.
            </p>
          </Row>
          <Row label="AiBox · AI가 만든 내용을 감싸는 점선 상자">
            <AiBox label="AI 생성 설명">
              하나의 연결을 여러 요청이 나눠 쓰는 방식이에요. 합성 문구 예시예요.
            </AiBox>
          </Row>
        </Section>

        <Section title="4. 입력 칸과 카드">
          <Row label="Field · 한 줄 / 여러 줄 / 비활성">
            <div style={{ display: 'grid', gap: 12 }}>
              <Field label="이메일" type="email" placeholder="name@example.com" autoComplete="off" />
              <Field label="내 답" multiline placeholder="답을 입력해요" />
              <Field label="비활성" disabled defaultValue="입력할 수 없어요" />
            </div>
          </Row>
          <Row label="Card">
            <Card>
              <h3 className={styles.cardTitle}>오늘 풀 퀴즈가 없어요</h3>
              <p className={styles.bodySmall}>노트에서 용어를 열어 보면 다음 날 퀴즈가 만들어져요.</p>
              <LinkButton to={devPaths.componentShowcase} variant="primary">
                노트 보러 가기
              </LinkButton>
            </Card>
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
                <Card>
                  <div className={styles.cardBadges}>
                    <Badge tone="ai">AI 생성</Badge>
                    <DifficultyChip level="mid" />
                  </div>
                  <h3 className={styles.cardTitle}>DNS를 한 문장으로 설명해 보세요.</h3>
                  <Field label="내 답" multiline placeholder="답을 입력해요" />
                  <div className={styles.cardActions}>
                    <Button variant="primary">답하기</Button>
                    <Button variant="report">오류 신고</Button>
                  </div>
                </Card>
              </div>
            </div>
          </Row>
        </Section>
      </div>

      <BottomSheet
        open={sheet === 'dictionary'}
        onClose={() => setSheet(null)}
        badge={<Badge tone="dictionary">사전</Badge>}
        title={<GlossaryTerm>DNS</GlossaryTerm>}
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
        badge={<Badge tone="ai">AI 생성</Badge>}
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
