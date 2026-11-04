// F5-1c 용어 사전 / F5-1e 새 용어(MEG-82). 왼쪽 목록에서 용어를 고르고 오른쪽 폼으로 등록·수정·삭제한다.
import { useEffect, useState } from 'react'
import { Link, useMatch, useNavigate, useParams } from 'react-router'
import { Button, StateMessage } from '../../components/index.ts'
import { glossaryTermPath, operatorPaths } from '../../routes/paths.ts'
import { useOperatorApi } from '../useOperatorApi.ts'
import { listTerms } from './glossaryApi.ts'
import type { GlossaryTerm } from './glossaryApi.ts'
import TermForm from './TermForm.tsx'
import styles from './Glossary.module.css'

type Load = { status: 'loading' } | { status: 'error' } | { status: 'ready'; terms: GlossaryTerm[] }

export default function GlossaryPage() {
  const navigate = useNavigate()
  const operatorFetch = useOperatorApi()
  const { termId } = useParams()
  const creating = useMatch(operatorPaths.glossaryNew) !== null
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [notice, setNotice] = useState<{ text: string; failed: boolean } | null>(null)
  const [attempt, setAttempt] = useState(0)
  // 저장하면 폼을 새로 그려 서버에 저장된 설명·이미지를 다시 읽는다.
  const [formVersion, setFormVersion] = useState(0)

  useEffect(() => {
    let current = true
    // 권한 상실(401·403)이면 operatorFetch가 이미 로그인 상태를 다시 읽는다. 여기서는 일반 실패와 같이 다룬다.
    listTerms(operatorFetch).then(
      (terms) => current && setLoad({ status: 'ready', terms }),
      () => current && setLoad({ status: 'error' }),
    )
    return () => {
      current = false
    }
  }, [attempt, operatorFetch])

  if (load.status === 'loading') {
    return (
      <main>
        <h1 className={styles.title}>용어 사전</h1>
        <StateMessage kind="loading" title="용어를 불러오는 중이에요" />
      </main>
    )
  }
  if (load.status === 'error') {
    return (
      <main>
        <h1 className={styles.title}>용어 사전</h1>
        <StateMessage
          kind="error"
          title="용어를 불러오지 못했어요"
          description="잠시 뒤에 다시 시도해 주세요."
          action={
            <Button
              onClick={() => {
                setLoad({ status: 'loading' })
                setAttempt((count) => count + 1)
              }}
            >
              다시 시도
            </Button>
          }
        />
      </main>
    )
  }

  const { terms } = load
  // 용어를 고르지 않았으면 첫 용어를 연다. 새 용어 화면에서는 고른 용어가 없다.
  const selected = creating ? null : termId ? (terms.find((term) => String(term.id) === termId) ?? null) : (terms[0] ?? null)
  const missing = !creating && termId !== undefined && selected === null

  // 저장·삭제 응답은 늦게 올 수 있어, 응답을 부른 시점의 목록(terms)이 아니라 지금의 목록에 반영한다.
  function updateTerms(change: (terms: GlossaryTerm[]) => GlossaryTerm[]) {
    setLoad((old) => (old.status === 'ready' ? { status: 'ready', terms: change(old.terms) } : old))
  }

  // 설명은 저장됐다. imageError가 있으면 이미지 단계만 실패한 것이라 그 안내를 보인다.
  // current가 false면 응답이 왔을 때 그 폼은 이미 화면에 없다(다른 용어를 열었다). 서버에서 끝난 저장이므로 목록과 안내는 갱신하되,
  // 지금 보는 폼을 다시 그리거나 그 용어로 이동하지 않는다(다른 용어에 쓰던 입력이 사라지지 않게).
  function afterSave(saved: GlossaryTerm, imageError: string | null, current: boolean) {
    updateTerms((list) => (list.some((term) => term.id === saved.id) ? list.map((term) => (term.id === saved.id ? saved : term)) : [saved, ...list]))
    const prefix = current ? '' : `‘${saved.label}’ `
    setNotice(imageError ? { text: `${prefix}${imageError}`, failed: true } : { text: `${prefix}사전 설명을 저장했어요.`, failed: false })
    if (!current) return
    setFormVersion((version) => version + 1)
    navigate(glossaryTermPath(saved.id))
  }

  function afterDelete(deleted: GlossaryTerm, current: boolean) {
    updateTerms((list) => list.filter((term) => term.id !== deleted.id))
    setNotice({ text: `${current ? '' : `‘${deleted.label}’ `}사전 설명을 삭제했어요.`, failed: false })
    if (current) navigate(operatorPaths.glossaryNew)
  }

  return (
    <main>
      <h1 className={styles.title}>용어 사전</h1>
      <div className={styles.layout}>
        <section className={styles.card} aria-label="용어 목록">
          <div className={`${styles.row} ${styles.spread}`}>
            <h2 className={styles.listTitle}>용어 {terms.length}개</h2>
            <Link to={operatorPaths.glossaryNew} aria-current={creating ? 'page' : undefined} className={styles.newTerm}>
              새 용어
            </Link>
          </div>
          <ul className={styles.list}>
            {terms.map((term) => (
              <li key={term.id}>
                <Link to={glossaryTermPath(term.id)} aria-current={selected?.id === term.id ? 'page' : undefined} className={styles.item}>
                  {term.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
        <div className={styles.formColumn}>
          {notice ? (
            notice.failed ? (
              <p role="alert" className={styles.error}>
                오류: {notice.text}
              </p>
            ) : (
              <p role="status" className={styles.status}>
                {notice.text}
              </p>
            )
          ) : null}
          {missing ? (
            <StateMessage kind="empty" title="찾을 수 없는 용어예요" description="목록에서 용어를 골라 주세요." />
          ) : (
            // 용어를 바꾸면 폼을 새로 그려 이전 입력이 남지 않게 한다.
            <TermForm
              key={`${selected?.id ?? 'new'}:${formVersion}`}
              term={selected}
              terms={terms}
              onSaved={afterSave}
              onDeleted={afterDelete}
              onCancel={() => navigate(operatorPaths.glossary)}
            />
          )}
        </div>
      </div>
    </main>
  )
}
