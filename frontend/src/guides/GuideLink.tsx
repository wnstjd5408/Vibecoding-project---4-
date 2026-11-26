// 노트 본문 첫머리의 가이드 연결 (MEG-288, PRD v0.5 AC-8·AC-10, 캔버스 G0-1m·G0-1·G1-E1m).
// 누르면 가이드 화면과 파일을 먼저 불러오고, 다 받은 뒤에 이동한다. 불러오지 못하면 노트에 그대로 남아 오류와 다시 시도를 보인다.
// 링크(a href)로 두어 새 탭에서 열기도 된다. 새 탭은 주소로 바로 들어온 경우와 같다.
import { useEffect, useId, useRef, useState, type MouseEvent } from 'react'
import { useNavigate } from 'react-router'
import { Button } from '../components/index.ts'
import { guidePath } from '../routes/paths.ts'
import { preloadGuide, type GuideEntryState } from './catalog.ts'
import type { GuideIndexEntry } from './types.ts'
import styles from './GuideLink.module.css'

const MESSAGES = {
  eyebrow: '단계별 가이드',
  open: '가이드 열기',
  opening: '여는 중…',
  errorEyebrow: '오류',
  failed: '가이드를 불러오지 못했어요. 노트는 그대로 읽을 수 있어요.',
  retry: '다시 시도',
}

export type GuideLinkProps = {
  guide: GuideIndexEntry
  // 이동하기 직전에 부른다. 노트 화면이 읽던 위치를 적어 둔다(돌아오면 되살린다).
  onLeave?: () => void
}

export function GuideLink({ guide, onLeave }: GuideLinkProps) {
  const navigate = useNavigate()
  const [state, setState] = useState<'idle' | 'opening' | 'failed'>('idle')
  const href = guidePath(guide.slug)
  // 불러오는 동안 사용자가 노트를 떠나면(뒤로 가기, 목록, 다른 노트) 다 받은 뒤에도 이동하지 않는다.
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  // 화면 묶음을 받지 못한 실패는 같은 탭에서 다시 받아도 실패할 수 있다. 두 번째 실패부터 다시 시도는 페이지를 새로 고친다.
  const failures = useRef(0)
  // 상태가 바뀌면 누를 곳(링크·다시 시도)이 새로 그려진다. 키보드 포커스가 카드 안에 있었으면 새 누를 곳으로 옮긴다(PRD AC-4).
  const cardRef = useRef<HTMLDivElement>(null)
  const refocus = useRef(false)
  const titleId = useId()
  useEffect(() => {
    if (!refocus.current) return
    refocus.current = false
    cardRef.current?.querySelector<HTMLElement>('[data-guide-link]')?.focus({ preventScroll: true })
  }, [state])

  const open = () => {
    if (state === 'opening') return
    if (failures.current >= 2) return window.location.reload()
    refocus.current = cardRef.current?.contains(document.activeElement) ?? false
    setState('opening')
    preloadGuide(guide.slug).then(
      () => {
        if (!mounted.current) return
        onLeave?.()
        navigate(href, { state: { from: 'note', noteId: guide.note_id } satisfies GuideEntryState })
      },
      () => {
        if (!mounted.current) return
        failures.current += 1
        refocus.current = cardRef.current?.contains(document.activeElement) ?? false
        setState('failed')
      },
    )
  }

  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    // 새 탭·새 창으로 여는 조작은 브라우저에 맡긴다.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    open()
  }

  if (state === 'failed') {
    return (
      <div ref={cardRef} className={styles.card} data-failed="" role="alert">
        <div className={styles.text}>
          <div className={styles.errorEyebrow}>{MESSAGES.errorEyebrow}</div>
          <div className={styles.errorBody}>{MESSAGES.failed}</div>
        </div>
        <Button variant="primary" onClick={open} data-guide-link="">
          {MESSAGES.retry}
        </Button>
      </div>
    )
  }

  return (
    <div ref={cardRef} className={styles.card}>
      <div className={styles.text}>
        <div className={styles.eyebrow}>{MESSAGES.eyebrow}</div>
        <div id={titleId} className={styles.title}>{guide.title}</div>
      </div>
      <a className={styles.open} href={href} onClick={onClick} aria-describedby={titleId} aria-disabled={state === 'opening' || undefined} data-guide-link="">
        {state === 'opening' ? MESSAGES.opening : MESSAGES.open}
      </a>
      {/* 여는 중임을 화면 낭독기에 알린다. 링크 글자가 바뀌는 것만으로는 알려지지 않는다. */}
      <span className={styles.visuallyHidden} role="status">{state === 'opening' ? MESSAGES.opening : ''}</span>
    </div>
  )
}
