// 노트 본문 첫머리의 가이드 연결 (MEG-288, PRD v0.5 AC-8·AC-10, 캔버스 G0-1m·G0-1·G1-E1m).
// 누르면 가이드 화면과 파일을 먼저 불러오고, 다 받은 뒤에 이동한다. 불러오지 못하면 노트에 그대로 남아 오류와 다시 시도를 보인다.
// 링크(a href)로 두어 새 탭에서 열기도 된다. 새 탭은 주소로 바로 들어온 경우와 같다.
import { useState, type MouseEvent } from 'react'
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

  const open = () => {
    if (state === 'opening') return
    setState('opening')
    preloadGuide(guide.slug).then(
      () => {
        onLeave?.()
        navigate(href, { state: { from: 'note' } satisfies GuideEntryState })
      },
      () => setState('failed'),
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
      <div className={styles.card} data-failed="" role="alert">
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
    <div className={styles.card}>
      <div className={styles.text}>
        <div className={styles.eyebrow}>{MESSAGES.eyebrow}</div>
        <div className={styles.title}>{guide.title}</div>
      </div>
      <a className={styles.open} href={href} onClick={onClick} aria-disabled={state === 'opening' || undefined} data-guide-link="">
        {state === 'opening' ? MESSAGES.opening : MESSAGES.open}
      </a>
    </div>
  )
}
