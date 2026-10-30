// F5-1c 용어 사전 / F5-1e 새 용어(MEG-82). 왼쪽 목록에서 용어를 고르고 오른쪽 폼으로 등록·수정·삭제한다.
import { useEffect, useState } from 'react'
import { Link, useMatch, useNavigate, useParams } from 'react-router'
import { Button, StateMessage } from '../../components/index.ts'
import { glossaryTermPath, operatorPaths } from '../../routes/paths.ts'
import { useOperatorGuard } from '../useOperatorGuard.ts'
import { listTerms } from './glossaryApi.ts'
import type { GlossaryTerm } from './glossaryApi.ts'
import TermForm from './TermForm.tsx'
import styles from './Glossary.module.css'

type Load = { status: 'loading' } | { status: 'error' } | { status: 'ready'; terms: GlossaryTerm[] }

export default function GlossaryPage() {
  const navigate = useNavigate()
  const { onApiError } = useOperatorGuard()
  const { termId } = useParams()
  const creating = useMatch(operatorPaths.glossaryNew) !== null
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [notice, setNotice] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let current = true
    listTerms().then(
      (terms) => current && setLoad({ status: 'ready', terms }),
      (failure) => {
        if (!current || onApiError(failure)) return
        setLoad({ status: 'error' })
      },
    )
    return () => {
      current = false
    }
  }, [attempt, onApiError])

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

  function afterSave(saved: GlossaryTerm) {
    setLoad({ status: 'ready', terms: terms.some((term) => term.id === saved.id) ? terms.map((term) => (term.id === saved.id ? saved : term)) : [...terms, saved] })
    setNotice('사전 설명을 저장했어요.')
    navigate(glossaryTermPath(saved.id))
  }

  function afterDelete(deleted: GlossaryTerm) {
    setLoad({ status: 'ready', terms: terms.filter((term) => term.id !== deleted.id) })
    setNotice('사전 설명을 삭제했어요.')
    navigate(operatorPaths.glossaryNew)
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
            <p role="status" className={styles.status}>
              {notice}
            </p>
          ) : null}
          {missing ? (
            <StateMessage kind="empty" title="찾을 수 없는 용어예요" description="목록에서 용어를 골라 주세요." />
          ) : (
            // 용어를 바꾸면 폼을 새로 그려 이전 입력이 남지 않게 한다.
            <TermForm
              key={selected?.id ?? 'new'}
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
