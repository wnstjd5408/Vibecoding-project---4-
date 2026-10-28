import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { aiDescription, filterNotes, noteBody, subjects } from './data.ts'
import { usePreview } from './model.ts'
import { useGo } from './useGo.ts'
import type { ScreenId } from './screens.ts'
import { Badge, Button, Card, Dialog, Field, IconButton, ImagePlaceholder } from './ui.tsx'
import styles from './mockup.module.css'

export function Header({ back, signed = false, operator = false, noAccount = false, menuInitiallyOpen = false, actions, operatorLink = false }: { back?: { label: string; id: ScreenId }; signed?: boolean; operator?: boolean; noAccount?: boolean; menuInitiallyOpen?: boolean; actions?: ReactNode; operatorLink?: boolean }) {
  const go = useGo()
  const model = usePreview()
  const [menu, setMenu] = useState(menuInitiallyOpen)
  return <header className={`${styles.header} ${back ? styles.headerBack : signed ? styles.headerSigned : ''}`}>
    {back ? <Button variant="text" onClick={() => go(back.id)}>{back.label}</Button> : <div className={styles.row}><span className={styles.brand}>CS 학습 노트</span>{operator && <Badge>운영자</Badge>}</div>}
    {!noAccount && <div className={`${styles.row} ${styles.smallGap}`}>
      {!operator && (operatorLink || model.role === 'operator') && !back && <Button variant="text" onClick={() => go('F5-1a')}>운영자 메뉴</Button>}
      {signed || operator || model.role !== 'visitor' ? <IconButton icon="account" label={menu ? '내 계정 메뉴 닫기' : '내 계정'} aria-expanded={menu} aria-haspopup="true" onClick={() => setMenu(!menu)} /> : <Button onClick={() => go('F4-1')}>로그인</Button>}
    </div>}
    {actions}
    {menu && <div className={styles.accountMenu} aria-label="내 계정" onKeyDown={(event) => { if (event.key === 'Escape') setMenu(false) }}>
      <Button variant="text" onClick={() => go(operator ? 'F4-3d' : 'F4-5')}>내 정보</Button>
      <Button variant="text" onClick={() => { model.setRole('visitor'); setMenu(false); go('F1-1') }}>로그아웃</Button>
    </div>}
  </header>
}

export function LoginPrompt({ quiz = false, close }: { quiz?: boolean; close: () => void }) {
  const go = useGo()
  return <Dialog title={quiz ? '로그인하세요' : '로그인이 필요해요'} close={close}>
    <div className={styles.stack}><h2>{quiz ? '로그인하세요' : '로그인이 필요해요'}</h2>
      <p className={styles.muted}>{quiz ? '오늘의 퀴즈는 로그인한 뒤에 볼 수 있어요. 계정은 운영자가 만들어 줘요.' : '로그인하면 AI 설명, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요. 계정은 운영자가 만들어 줘요.'}</p>
      <Button variant="solid" onClick={() => go('F4-1')}>로그인</Button></div>
  </Dialog>
}

export function NoteList({ id }: { id: ScreenId }) {
  const model = usePreview()
  const go = useGo()
  const [subject, setSubject] = useState('전체')
  const [prompt, setPrompt] = useState(id === 'F1-1c')
  const signed = id === 'F1-1b' || model.role !== 'visitor'
  const filtered = filterNotes(model.notes, subject)
  const notes = id === 'F1-1c' && prompt ? filtered.slice(0, 2) : filtered
  return <>
    <Header signed={signed} operatorLink={id === 'F1-1b'} />
    <div className={styles.sectionTitle}><h1>과목</h1></div>
    <div className={styles.filters}>{['전체', ...subjects].map((name) => <Button key={name} className={styles.chip} aria-pressed={subject === name} onClick={() => setSubject(name)}>{name}</Button>)}</div>
    <div className={styles.quizLink}><Button variant="text" className={styles.link} onClick={() => signed ? go('F3-3a') : setPrompt(true)}>오늘의 퀴즈</Button></div>
    <div className={styles.noteList}>{notes.map((note) => <button key={note.id} className={styles.noteItem} onClick={() => { model.setNoteId(note.id); go('F1-2') }}><div className={styles.noteTitle}>{note.title}</div><div className={styles.metadata}>{note.subjects.join(' · ')} · {note.date}</div></button>)}{notes.length === 0 && <p className={styles.empty}>이 과목에는 노트가 없어요.</p>}</div>
    {prompt && <LoginPrompt quiz close={() => setPrompt(false)} />}
  </>
}

export function ReportDialog({ close, kind = '용어 설명' }: { close: () => void; kind?: '용어 설명' | '퀴즈 문항' }) {
  const model = usePreview()
  const [reason, setReason] = useState('')
  return <Dialog title="오류 신고" close={close}><form className={styles.stack} onSubmit={(event) => { event.preventDefault(); model.setReports((old) => [...old, { id: Date.now(), kind, title: kind === '용어 설명' ? '멀티플렉싱' : 'DNS 퀴즈', body: reason.trim(), resolved: false }]); model.setNotice('신고를 남겼어요.'); close() }}>
    <h2>오류 신고</h2><label className={styles.label} htmlFor="report-reason">어떤 내용이 잘못되었나요?</label><textarea id="report-reason" className={styles.textarea} value={reason} onChange={(event) => setReason(event.target.value)} required maxLength={2000} /><Button variant="danger" type="submit" disabled={!reason.trim()}>신고하기</Button>
  </form></Dialog>
}

export function TermContent({ ai = false, full = false, initiallySaved = false, signed = false, onLogin }: { ai?: boolean; full?: boolean; initiallySaved?: boolean; signed?: boolean; onLogin: () => void }) {
  const model = usePreview()
  const go = useGo()
  const term = model.terms.find(({ id }) => id === model.termId) ?? model.terms[0]
  const [saved, setSaved] = useState(initiallySaved || model.favorites.includes(model.termId))
  const [report, setReport] = useState(false)
  const label = ai ? '멀티플렉싱' : term?.label ?? 'DNS'
  return <>
    <div className={styles.termBody}>
      <Badge>{ai ? 'AI 생성' : '사전'}</Badge>
      {full ? <h1>{label}</h1> : <h2>{ai ? label : <span className={styles.term}>{label}</span>}</h2>}
      <div className={ai ? styles.aiBox : undefined}><p>{ai ? aiDescription : `${term?.description ?? ''} 합성 문구 예시예요.`}</p></div>
      {!ai && (term?.image ? <img className={styles.termImage} src={term.image} alt={`${label} 설명 이미지`} /> : <ImagePlaceholder />)}
      {!full && <div className={styles.row}>
        <IconButton icon="star" label="즐겨찾기" aria-pressed={saved} onClick={() => { if (!signed && model.role === 'visitor') { onLogin(); return } setSaved(!saved); model.setFavorites((old) => saved ? old.filter((id) => id !== model.termId) : [...new Set([...old, model.termId])]) }} />
        {!full && <IconButton icon="expand" label="전체 보기" onClick={() => go(ai ? 'F2-2c' : saved ? 'F1-3c' : 'F1-3b')} />}
        {ai && <IconButton icon="report" label="오류 신고" onClick={() => setReport(true)} />}
      </div>}
    </div>
    {report && <ReportDialog close={() => setReport(false)} />}
  </>
}

export function NoteRead({ id }: { id: ScreenId }) {
  const go = useGo()
  const model = usePreview()
  const note = model.notes.find(({ id }) => id === model.noteId) ?? model.notes[0]
  const [sheet, setSheet] = useState<'term' | 'ai' | 'login' | null>(id === 'F1-3' || id === 'F3-2' ? 'term' : id === 'F2-2a' ? 'ai' : id === 'F2-2b' ? 'login' : null)
  const [selection, setSelection] = useState(id === 'F2-1')
  const signed = ['F2-1', 'F2-2a', 'F3-2'].includes(id) || model.role !== 'visitor'
  const openTerm = (label: string) => { const term = model.terms.find((item) => item.label === label); if (term) model.setTermId(term.id); setSheet('term') }
  const termLink = (label: string) => <button className={styles.term} onClick={() => openTerm(label)}>{label}</button>
  return <>
    <Header back={{ label: '목록', id: signed ? 'F1-1b' : 'F1-1' }} signed={signed} />
    <main className={`${styles.content} ${styles.article}`} onMouseUp={() => { if (window.getSelection()?.toString().trim()) setSelection(true) }}>
      <h1>{note?.title}</h1><div className={styles.noteMeta}>{note?.subjects.join(' · ')} · {note?.date}</div>
      {note?.id === 11 && note.body === noteBody ? <>{!(['F2-2a', 'F2-2b'].includes(id) && sheet) && <p>브라우저가 주소를 입력받으면 먼저 {termLink('DNS')}에 물어 서버의 위치를 찾아요. 찾은 위치로 {termLink('패킷')}을 보내면 {termLink('라우터')}가 길을 골라 전달해요.</p>}
        {id === 'F1-3' && sheet ? <p>같은 요청이 반복되면 캐시가 이전 응답을 다시 써서 시간을 줄여요.</p> : <p>같은 요청이 반복되면 {termLink('캐시')}가 이전 응답을 다시 써서 시간을 줄여요. 한 연결로 여러 요청을 묶어 보내는 <button className={styles.text} style={{ padding: 0, font: 'inherit', color: 'inherit' }} onClick={() => setSelection(!selection)} aria-expanded={selection}>멀티플렉싱</button>도 같은 목적이에요.</p>}
        {selection && <Button variant="solid" className={styles.selectionAction} onClick={() => setSheet(signed ? 'ai' : 'login')}>AI 설명</Button>}
        {!(['F1-3', 'F2-2a', 'F2-2b', 'F3-2'].includes(id) && sheet) && <><code className={styles.code}>curl -I example.test</code><p>응답 헤더에서 캐시 관련 값을 확인하면 이전에 받은 응답을 다시 썼는지 알 수 있어요.</p></>}</> : <p>{note?.body}</p>}
    </main>
    {(sheet === 'term' || sheet === 'ai') && <Dialog title={sheet === 'ai' ? 'AI 설명' : '사전 용어 설명'} close={() => setSheet(null)}><TermContent ai={sheet === 'ai'} initiallySaved={id === 'F3-2'} signed={signed} onLogin={() => setSheet('login')} /></Dialog>}
    {sheet === 'login' && <LoginPrompt close={() => setSheet(null)} />}
    {!note && <Button onClick={() => go('F1-1')}>목록으로</Button>}
  </>
}

export function FullTerm({ id }: { id: ScreenId }) {
  const [login, setLogin] = useState(false)
  const [report, setReport] = useState(false)
  const model = usePreview()
  const ai = id === 'F2-2c'
  const [saved, setSaved] = useState(id === 'F1-3c' || model.favorites.includes(model.termId))
  const toggle = () => {
    if (!ai && id !== 'F1-3c' && model.role === 'visitor') { setLogin(true); return }
    setSaved(!saved)
    model.setFavorites((old) => saved ? old.filter((key) => key !== model.termId) : [...new Set([...old, model.termId])])
  }
  return <><Header back={{ label: '시트로 돌아가기', id: ai ? 'F2-2a' : id === 'F1-3c' ? 'F3-2' : 'F1-3' }} noAccount actions={<div className={styles.row}><IconButton icon="star" label="즐겨찾기" aria-pressed={saved} onClick={toggle} />{ai && <Button variant="danger" onClick={() => setReport(true)}>오류 신고</Button>}</div>} /><main className={`${styles.content} ${styles.fullTerm}`}><TermContent ai={ai} full onLogin={() => setLogin(true)} /></main>{login && <LoginPrompt close={() => setLogin(false)} />}{report && <ReportDialog close={() => setReport(false)} />}</>
}

export function Login() {
  const go = useGo()
  const model = usePreview()
  const [error, setError] = useState('')
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const email = String(data.get('email')).trim()
    // Preview-only credentials. Never sends a password or creates a server session.
    if (!['member@example.test', 'operator@example.test'].includes(email) || data.get('password') !== 'example-password') { setError('이메일 또는 비밀번호를 확인해 주세요.'); return }
    model.setRole(email.startsWith('operator') ? 'operator' : 'member')
    event.currentTarget.reset()
    go(email.startsWith('operator') ? 'F1-1b' : 'F3-3a')
  }
  return <><Header noAccount /><main className={`${styles.content} ${styles.login}`}><div className={styles.stack}><h1>로그인</h1><p className={styles.muted}>계정은 운영자가 만들어 줘요. 직접 가입하는 기능은 없어요.</p><form className={styles.stack} onSubmit={submit}>
    <Field label="이메일" name="email" type="email" autoComplete="username" placeholder="name@example.com" required />
    <Field label="비밀번호" name="password" type="password" autoComplete="current-password" required />
    {error && <p role="alert" className={styles.error}>{error}</p>}<Button type="submit" variant="solid">로그인</Button>
  </form><Button variant="text" className={styles.link} onClick={() => go('F1-1')}>로그인 없이 노트 보기</Button></div></main></>
}

export function Quiz({ id }: { id: ScreenId }) {
  const model = usePreview()
  const go = useGo()
  const [draft, setDraft] = useState('')
  const [step, setStep] = useState(1)
  const [done, setDone] = useState(false)
  const [report, setReport] = useState(false)
  const empty = id === 'F3-3b' || id === 'F4-4' || done
  const follow = id === 'F3-5'
  const submit = (event: FormEvent) => { event.preventDefault(); if (!draft.trim()) return; if (follow) { if (step === 2) setDone(true); else setStep(2); setDraft('') } else { model.setAnswer(draft); go('F3-4') } }
  return <><Header signed menuInitiallyOpen={id === 'F4-4'} /><main className={styles.content}>
    <div className={styles.quizHeading}><h1>오늘의 퀴즈</h1>{!empty && <p className={styles.muted}>어제 열어 본·즐겨찾기한 용어로 만들었어요.</p>}</div>
    {empty ? <Card><div className={styles.stack}><h3>{done ? '오늘의 퀴즈를 마쳤어요' : '오늘 풀 퀴즈가 없어요'}</h3><p className={styles.muted}>노트에서 용어를 열어 보면 다음 날 퀴즈가 만들어져요.</p><Button variant="solid" onClick={() => go('F1-1b')}>노트 보러 가기</Button></div></Card> : <Card><form className={styles.quizCard} onSubmit={submit}>
      <div className={`${styles.row} ${styles.smallGap}`}><Badge>AI 생성</Badge>{follow ? <Badge>꼬리 질문 {step}/2</Badge> : <Badge difficulty>난이도 중</Badge>}</div>
      <h3>{follow ? step === 1 ? '합성 꼬리 질문 예시: 방금 답에서 왜 그렇게 생각했나요?' : '합성 꼬리 질문 예시: 다른 상황에도 적용할 수 있을까요?' : 'DNS를 한 문장으로 설명해 보세요.'}</h3>
      {follow && <p className={styles.muted}>꼬리 질문은 맞고 틀림을 채점하지 않아요.</p>}
      {id === 'F3-4' ? <><div><span className={styles.label}>내 답</span><p className={styles.answer}>{model.answer || '합성 답변 예시예요. 사용자가 쓴 답이 여기에 보여요.'}</p></div><div className={styles.aiBox}><h3>정답과 해설</h3><p className={styles.answer}>정답과 해설이 여기에 들어가요. 합성 문구 예시예요.</p></div></> : <div><label className={styles.label} htmlFor="quiz-answer">내 답</label><textarea id="quiz-answer" className={styles.textarea} placeholder="답을 입력해요" value={draft} onChange={(event) => setDraft(event.target.value)} required maxLength={4000} /></div>}
      <div className={styles.row}>{id === 'F3-4' ? <Button variant="solid" onClick={() => go('F3-5')}>다음</Button> : <Button variant="solid" type="submit" disabled={!draft.trim()}>답하기</Button>}<Button variant="danger" onClick={() => setReport(true)}>오류 신고</Button></div>
    </form></Card>}
    {id === 'F3-3a' && <Button variant="text" className={styles.link} onClick={() => go('F1-1b')}>노트 보러 가기</Button>}
  </main>{report && <ReportDialog kind="퀴즈 문항" close={() => setReport(false)} />}</>
}

export function AccountInfo({ operator = false }: { operator?: boolean }) {
  return <div className={styles.stack}><h1>내 정보</h1><Card><h3>계정</h3><dl className={styles.details}>{[['표시 이름', operator ? '합성 운영자' : '합성 사용자'], ['이메일', operator ? 'operator@example.test' : 'member@example.test'], ['역할', operator ? '운영자' : '일반 사용자']].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p className={styles.hint}>{operator ? '이 화면에서는 볼 수만 있어요.' : '운영자가 만든 계정 정보예요. 이 화면에서는 볼 수만 있어요.'}</p></Card></div>
}

export function MobilePage({ id }: { id: ScreenId }) {
  let content: ReactNode
  if (['F1-1', 'F1-1b', 'F1-1c'].includes(id)) content = <NoteList id={id} />
  else if (['F1-3b', 'F1-3c', 'F2-2c'].includes(id)) content = <FullTerm id={id} />
  else if (id === 'F4-1') content = <Login />
  else if (id === 'F4-5') content = <><Header back={{ label: '돌아가기', id: 'F3-3b' }} noAccount /><main className={styles.content}><AccountInfo /></main></>
  else if (['F3-3a', 'F3-3b', 'F3-4', 'F3-5', 'F4-4'].includes(id)) content = <Quiz id={id} />
  else content = <NoteRead id={id} />
  return <div className={styles.mobile}>{content}</div>
}
