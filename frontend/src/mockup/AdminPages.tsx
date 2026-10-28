import { useEffect, useId, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router'
import { filterNotes, saveItem, subjects } from './data.ts'
import type { Note, Term } from './data.ts'
import { usePreview } from './model.ts'
import { AccountInfo, Header } from './MobilePages.tsx'
import { useGo } from './useGo.ts'
import { previewPath } from './screens.ts'
import type { ScreenId } from './screens.ts'
import { Badge, Button, Card, Dialog, Field, IconButton, ImagePlaceholder } from './ui.tsx'
import styles from './mockup.module.css'

const navigation: [ScreenId, string][] = [['F5-1a', '노트'], ['F5-1c', '용어 사전'], ['F5-2', '신고'], ['F4-3a', '계정 발급']]

function DeleteNote({ close }: { close: () => void }) {
  const model = usePreview()
  const go = useGo()
  const note = model.adminNotes.find(({ id }) => id === model.noteId)
  return <Dialog title="노트를 삭제할까요?" close={close} centered><div className={styles.stack}><Badge>문구 미정</Badge><h2>노트를 삭제할까요?</h2><p>{note?.title}</p><p className={styles.muted}>삭제하면 이 노트로 만든 AI 설명이 무효가 되고, 노트의 이미지 파일도 삭제 대상이 돼요.</p><div className={styles.row}><Button variant="solid" onClick={() => { model.setAdminNotes((old) => old.filter(({ id }) => id !== model.noteId)); model.setNotes((old) => old.filter(({ id }) => id !== model.noteId)); model.setNotice('노트를 삭제했어요.'); go('F5-1a') }}>삭제하기</Button><Button onClick={close}>취소</Button></div></div></Dialog>
}

function AdminNotes({ deletion = false }: { deletion?: boolean }) {
  const model = usePreview()
  const go = useGo()
  const [subject, setSubject] = useState('전체')
  const [remove, setRemove] = useState(deletion)
  const notes = filterNotes(model.adminNotes, subject)
  return <><div className={`${styles.row} ${styles.spread} ${styles.adminTitle}`}><h1>노트</h1><div className={styles.row}><label className={styles.filterLabel} htmlFor="note-filter">과목</label><select id="note-filter" className={styles.filterSelect} value={subject} onChange={(event) => setSubject(event.target.value)}>{['전체', ...new Set(model.adminNotes.flatMap((note) => note.subjects))].map((name) => <option key={name}>{name}</option>)}</select><IconButton icon="plus" label="새 노트" variant="solid" onClick={() => go('F5-1d')} /></div></div>
    <div className={styles.tableWrap}><table className={styles.table}><caption>노트 {notes.length}개</caption><thead><tr><th scope="col">제목</th><th scope="col">과목</th><th scope="col">학습일</th><th scope="col">동작</th></tr></thead><tbody>{notes.map((note) => <tr key={note.id}><td><strong>{note.title}</strong></td><td>{note.subjects.join(' · ')}</td><td>{note.date}</td><td><div className={styles.row}><Button variant="text" className={styles.link} onClick={() => { model.setNoteId(note.id); go('F5-1b') }}>수정</Button><Button variant="text" className={styles.link} onClick={() => { model.setNoteId(note.id); setRemove(true) }}>삭제</Button></div></td></tr>)}</tbody></table>{!notes.length && <p className={styles.empty}>등록된 노트가 없어요.</p>}</div>
    {remove && <DeleteNote close={() => setRemove(false)} />}
  </>
}

function NoteEditor({ creating }: { creating: boolean }) {
  const model = usePreview()
  const go = useGo()
  const existing = model.adminNotes.find(({ id }) => id === model.noteId)
  const [draft, setDraft] = useState<Note>(() => creating || !existing ? { id: Date.now(), title: '', subjects: [], date: '', body: '', parent: '', sources: [''] } : { ...existing, sources: existing.sources.length ? [...existing.sources] : [''] })
  const [error, setError] = useState('')
  const [remove, setRemove] = useState(false)
  const bodyId = useId()
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!draft.title.trim() || !draft.body.trim() || !draft.subjects.length) { setError('제목, 과목, 본문을 입력해 주세요.'); return }
    const note = { ...draft, title: draft.title.trim(), sources: draft.sources.map((source) => source.trim()).filter(Boolean) }
    model.setAdminNotes((old) => saveItem(old, note)); model.setNotes((old) => saveItem(old, note)); model.setNotice('노트를 저장했어요.'); go('F5-1a')
  }
  return <><Button variant="text" className={styles.link} onClick={() => go('F5-1a')}>노트 목록으로</Button><div className={styles.adminTitle}><h1>{creating ? '새 노트' : '노트 수정'}</h1></div>
    <form className={`${styles.card} ${styles.formCard}`} onSubmit={submit}>
      <Field label="제목" value={draft.title} required maxLength={200} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
      <fieldset className={styles.fieldset}><legend className={styles.label}>과목 (여러 개 고를 수 있어요)</legend><div className={`${styles.row} ${styles.smallGap}`}>{subjects.map((name) => <label key={name} className={styles.checkChip}><input type="checkbox" checked={draft.subjects.includes(name)} onChange={(event) => setDraft({ ...draft, subjects: event.target.checked ? [...draft.subjects, name] : draft.subjects.filter((value) => value !== name) })} />{name}</label>)}</div></fieldset>
      <div className={styles.twoColumns}><Field label="학습일" type="date" value={draft.date} required onChange={(event) => setDraft({ ...draft, date: event.target.value })} /><label className={styles.label}>상위 노트<select className={styles.select} value={draft.parent} onChange={(event) => setDraft({ ...draft, parent: event.target.value })}><option value="">없음</option>{model.adminNotes.filter(({ id }) => id !== draft.id).map((note) => <option key={note.id} value={note.id}>{note.title}</option>)}</select></label></div>
      <div className={styles.stack}>{draft.sources.map((source, index) => <Field key={index} label={index ? `출처 링크 ${index + 1}` : '출처 링크'} type="url" value={source} placeholder="https://example.test/doc" onChange={(event) => setDraft({ ...draft, sources: draft.sources.map((old, i) => i === index ? event.target.value : old) })} />)}<div><Button onClick={() => setDraft({ ...draft, sources: [...draft.sources, ''] })}>출처 추가</Button></div></div>
      <div><label className={styles.label} htmlFor={bodyId}>본문</label><textarea id={bodyId} className={styles.textarea} style={{ minHeight: 200 }} required value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} /><p className={styles.hint}>이미지는 이 화면에서 올리지 않아요. 가져오기로만 들어와요.</p></div>
      {!creating && <p className={styles.notice}>안내: 제목이나 본문을 저장하면 이 노트로 만든 AI 설명이 무효가 돼요.</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}<div className={styles.row}><Button variant="solid" type="submit">저장</Button><Button onClick={() => go('F5-1a')}>취소</Button></div>
      {!creating && <div className={styles.divider}><Button onClick={() => setRemove(true)}>노트 삭제</Button></div>}
    </form>{remove && <DeleteNote close={() => setRemove(false)} />}
  </>
}

function ImageField({ draft, setDraft }: { draft: Term; setDraft: (value: Term) => void }) {
  const [error, setError] = useState('')
  const id = useId()
  return <div className={styles.stack}>
    {(draft.image || draft.placeholder) && <><span className={styles.label}>이미지</span><div className={styles.row}><div className={styles.imageRow}>{draft.image ? <img className={styles.termImage} src={draft.image} alt="설명 이미지 미리보기" /> : <ImagePlaceholder />}</div><Button onClick={() => setDraft({ ...draft, image: undefined, placeholder: false })}>이미지 삭제</Button></div></>}
    <div><label className={styles.label} htmlFor={id}>이미지 올리기 (선택, 한 장씩)</label><input id={id} type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => {
      const file = event.target.files?.[0]
      if (!file) return
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) { setError('5MB 이하의 PNG, JPG, WebP 이미지를 선택해 주세요.'); return }
      setError('')
      const reader = new FileReader()
      reader.onload = () => { if (typeof reader.result === 'string') setDraft({ ...draft, image: reader.result, placeholder: false }) }
      reader.onerror = () => setError('이미지를 읽지 못했어요. 다시 선택해 주세요.')
      reader.readAsDataURL(file)
    }} /></div>{error && <p role="alert" className={styles.error}>{error}</p>}
  </div>
}

function TermEditor({ creating, fromReport = false }: { creating: boolean; fromReport?: boolean }) {
  const model = usePreview()
  const go = useGo()
  const existing = model.terms.find(({ id }) => id === model.termId)
  const report = model.reports.find(({ id }) => id === model.reportId)
  const [draft, setDraft] = useState<Term>(() => creating || fromReport || !existing ? { id: Date.now(), label: fromReport ? report?.title ?? 'TCP' : '', description: '' } : { ...existing })
  const [error, setError] = useState('')
  const [remove, setRemove] = useState(false)
  const descId = useId()
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!draft.label.trim() || !draft.description.trim()) { setError('용어 이름과 설명을 입력해 주세요.'); return }
    const duplicate = model.terms.find((term) => term.label.toLowerCase() === draft.label.trim().toLowerCase() && term.id !== draft.id)
    if (duplicate && !fromReport) { setError('이미 등록된 용어예요. 목록에서 선택해 수정해 주세요.'); return }
    const term = { ...draft, id: duplicate?.id ?? draft.id, label: draft.label.trim() }
    model.setTerms((old) => saveItem(old, term)); model.setTermId(term.id); model.setNotice('사전 설명을 저장했어요.'); go(fromReport ? 'F5-2' : 'F5-1c')
  }
  return <form className={`${styles.card} ${styles.formCard} ${styles.glossaryForm}`} onSubmit={submit}>
    <h2>{fromReport ? '사전 설명' : creating ? '새 용어' : '용어 수정'}</h2>
    <Field label="용어 이름" required maxLength={100} value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} />
    <div><label className={styles.label} htmlFor={descId}>{fromReport ? '바른 설명' : '설명'}</label><textarea className={styles.textarea} id={descId} required value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></div>
    <ImageField draft={draft} setDraft={setDraft} />
    <p className={styles.notice}>{fromReport ? '안내: 저장하면 이 용어는 사전 설명이 먼저 보이고 AI 설명은 무효가 돼요. 신고 상태는 신고 목록에서 따로 바꿔요.' : creating ? '안내: 저장하면 같은 용어의 AI 설명이 무효가 돼요.' : '안내: 저장하면 이 용어의 AI 설명이 무효가 돼요. 용어를 삭제해도 AI 설명과 신고는 남아요.'}</p>
    {error && <p className={styles.error} role="alert">{error}</p>}<div className={styles.row}><Button type="submit" variant="solid">{fromReport ? '사전에 저장' : '저장'}</Button>{(creating || fromReport) && <Button onClick={() => go(fromReport ? 'F5-2' : 'F5-1c')}>취소</Button>}</div>
    {!creating && !fromReport && <div className={styles.divider}><Button onClick={() => setRemove(true)}>사전 설명 삭제</Button></div>}
    {remove && <Dialog title="사전 설명을 삭제할까요?" centered close={() => setRemove(false)}><div className={styles.stack}><h2>사전 설명을 삭제할까요?</h2><p>{draft.label}</p><div className={styles.row}><Button variant="danger" onClick={() => { model.setTerms((old) => old.filter(({ id }) => id !== draft.id)); model.setNotice('사전 설명을 삭제했어요.'); go('F5-1e') }}>삭제하기</Button><Button onClick={() => setRemove(false)}>취소</Button></div></div></Dialog>}
  </form>
}

function Glossary({ creating }: { creating: boolean }) {
  const model = usePreview()
  const go = useGo()
  return <><div className={styles.adminTitle}><h1>용어 사전</h1></div><div className={styles.glossaryLayout}>
    <Card className={styles.glossaryList}><div className={`${styles.row} ${styles.spread}`}><h3>용어 {model.terms.length}개</h3><Button onClick={() => go('F5-1e')}>새 용어</Button></div><ul>{model.terms.map((term) => <li key={term.id}><Button aria-current={!creating && term.id === model.termId ? 'true' : undefined} onClick={() => { model.setTermId(term.id); go('F5-1c') }}>{term.label}</Button></li>)}</ul></Card>
    <TermEditor key={`${creating}-${model.termId}`} creating={creating} />
  </div></>
}

function Accounts({ issued = false }: { issued?: boolean }) {
  const model = usePreview()
  const go = useGo()
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget)
    model.setIssued({ email: String(data.get('email')).trim(), name: String(data.get('name')).trim() })
    // Password is deliberately never copied into application state or storage.
    event.currentTarget.reset(); go('F4-3b')
  }
  return <><div className={styles.adminTitle}><h1>계정 발급</h1><p className={styles.muted} style={{ marginTop: 8, marginBottom: 24 }}>일반 사용자 계정을 만들어요. 가입 화면은 없어서 계정은 운영자만 발급해요.</p></div>
    {issued ? <Card className={`${styles.formCard} ${styles.accountForm}`}><h2>계정을 발급했어요</h2><dl className={styles.details}>{[['이메일', model.issued.email], ['표시 이름', model.issued.name], ['역할', '일반 사용자']].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p className={styles.notice}>안내: 비밀번호는 화면에 다시 보여 주지 않아요.</p><Button onClick={() => go('F4-3a')}>다른 계정 발급하기</Button></Card> : <form className={`${styles.card} ${styles.formCard} ${styles.accountForm}`} onSubmit={submit}>
      <Field name="email" label="이메일" type="email" placeholder="member@example.test" required />
      <Field name="name" label="표시 이름" placeholder="합성 사용자" required maxLength={80} />
      <Field name="password" label="초기 비밀번호" type="password" autoComplete="new-password" required minLength={8} hint="발급한 뒤에는 이 비밀번호를 다시 볼 수 없어요." />
      <p className={styles.hint}>발급한 계정은 일반 사용자예요. 운영자 계정은 이 화면에서 만들 수 없어요.</p><div><Button type="submit" variant="solid">발급하기</Button></div>
    </form>}
  </>
}

function Reports() {
  const model = usePreview()
  const go = useGo()
  const [resolved, setResolved] = useState(false)
  const reports = model.reports.filter((report) => report.resolved === resolved)
  return <><div className={`${styles.row} ${styles.spread} ${styles.adminTitle}`}><h1>신고</h1><div className={styles.row}><label className={styles.filterLabel} htmlFor="report-filter">상태</label><select id="report-filter" className={styles.filterSelect} value={String(resolved)} onChange={(event) => setResolved(event.target.value === 'true')}><option value="false">열림</option><option value="true">처리됨</option></select></div></div>
    <div className={styles.tableWrap}><table className={styles.table}><caption>{resolved ? '처리된' : '열린'} 신고 {reports.length}건</caption><thead><tr><th scope="col">종류</th><th scope="col">신고된 내용</th><th scope="col">동작</th></tr></thead><tbody>{reports.map((report) => <tr key={report.id}><td><Badge>AI 생성</Badge><p>{report.kind}</p></td><td><h3>{report.title}</h3><p>{report.body}</p></td><td><div className={styles.stack}>{report.kind === '용어 설명' && <Button onClick={() => { model.setReportId(report.id); go('F5-3') }}>사전에 바른 설명 넣기</Button>}<Button onClick={() => model.setReports((old) => old.map((item) => item.id === report.id ? { ...item, resolved: !resolved } : item))}>{resolved ? '다시 열기' : '처리됨으로 표시'}</Button></div></td></tr>)}</tbody></table>{reports.length === 0 && <p className={styles.empty}>이 상태의 신고가 없어요.</p>}</div>
  </>
}

function CorrectReport() {
  const go = useGo()
  const model = usePreview()
  const report = model.reports.find(({ id }) => id === model.reportId)
  return <><Button className={styles.link} variant="text" onClick={() => go('F5-2')}>신고 목록으로</Button><div className={styles.adminTitle}><h1>사전에 바른 설명 넣기</h1></div><div className={styles.stack}><Card className={styles.glossaryForm}><h3>신고된 AI 설명 · {report?.title}</h3><Badge>AI 생성</Badge><p className={styles.muted}>{report?.body}</p></Card><TermEditor creating fromReport /></div></>
}

export function AdminPage({ id }: { id: ScreenId }) {
  const active = id.startsWith('F4-3') ? '계정 발급' : ['F5-1c', 'F5-1e'].includes(id) ? '용어 사전' : ['F5-2', 'F5-3'].includes(id) ? '신고' : '노트'
  const model = usePreview()
  const { setRole } = model
  useEffect(() => { setRole('operator') }, [setRole])
  return <div className={styles.operator}><Header operator menuInitiallyOpen={id === 'F4-3c'} /><div className={styles.operatorBody}>
    <nav className={styles.sidebar} aria-label="운영자 메뉴">{navigation.map(([key, label]) => <Link key={key} to={previewPath(key)} className={styles.navItem} aria-current={active === label ? 'page' : undefined}>{label}</Link>)}</nav>
    <main className={styles.adminContent}>
      {['F4-3a', 'F4-3b', 'F4-3c'].includes(id) && <Accounts issued={id === 'F4-3b'} />}
      {id === 'F4-3d' && <AccountInfo operator />}
      {['F5-1a', 'F5-1f'].includes(id) && <AdminNotes deletion={id === 'F5-1f'} />}
      {['F5-1b', 'F5-1d'].includes(id) && <NoteEditor creating={id === 'F5-1d'} />}
      {['F5-1c', 'F5-1e'].includes(id) && <Glossary creating={id === 'F5-1e'} />}
      {id === 'F5-2' && <Reports />}{id === 'F5-3' && <CorrectReport />}
    </main>
  </div></div>
}
