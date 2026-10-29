// F4-4 계정 메뉴(MEG-65). 헤더 오른쪽의 사람 아이콘을 누르면 "내 정보"와 "로그아웃"이 아래로 열린다.
// 로그인한 사용자(member·operator)에게만 보여 준다. 로그인 여부로 이 메뉴와 로그인 버튼 중 무엇을 둘지는 화면이 정한다.
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { IconButton } from '../components/IconButton.tsx'
import { AccountIcon } from '../components/icons.tsx'
import { cx } from '../components/cx.ts'
import { useAuth } from '../auth/useAuth.ts'
import { userPaths } from '../routes/paths.ts'
import { checkLoggedOut, logout } from './logout.ts'
import styles from './AccountMenu.module.css'

// 로그아웃 안내. 목업에 화면이 없어 모두 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const MESSAGES = {
  // E02가 실패했거나, 성공했는데 아직 로그인 상태로 읽혔다. 로그아웃이 안 된 것이다. 다시 누르면 E02부터 다시 한다.
  failed: '로그아웃하지 못했어요. 잠시 뒤에 다시 시도해 주세요.',
  // E02는 성공했지만 E03을 받지 못했다. 이미 로그아웃됐을 수 있어 단정하지 않는다. 다시 확인하면 E03만 다시 읽는다.
  unconfirmed: '로그아웃했는지 확인하지 못했어요. 다시 확인해 주세요.',
  logout: '로그아웃',
  recheck: '로그아웃 여부 다시 확인',
} as const

// failed: 로그아웃이 안 됨, unconfirmed: 로그아웃했는지 확인하지 못함
type Failure = 'failed' | 'unconfirmed'

export function AccountMenu() {
  const navigate = useNavigate()
  const location = useLocation()
  const { refresh } = useAuth()
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)

  const items = () => Array.from(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])

  // 열리면 첫 항목으로 포커스를 옮긴다(ARIA 메뉴 버튼 패턴).
  useEffect(() => {
    if (open) items()[0]?.focus()
  }, [open])

  // 메뉴 바깥을 누르면 닫는다. 포커스는 누른 곳이 가져간다.
  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  function closeAndFocusTrigger() {
    setOpen(false)
    triggerRef.current?.focus()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const list = items()
    const index = list.indexOf(document.activeElement as HTMLElement)
    switch (event.key) {
      case 'Escape':
        event.preventDefault()
        closeAndFocusTrigger()
        break
      case 'ArrowDown':
        event.preventDefault()
        list[(index + 1) % list.length]?.focus()
        break
      case 'ArrowUp':
        event.preventDefault()
        list[(index - 1 + list.length) % list.length]?.focus()
        break
      case 'Home':
        event.preventDefault()
        list[0]?.focus()
        break
      case 'End':
        event.preventDefault()
        list[list.length - 1]?.focus()
        break
      case 'Tab':
        // 다음 요소로 포커스가 옮겨 가므로 메뉴만 닫는다.
        setOpen(false)
        break
    }
  }

  async function handleLogout() {
    // 한 번에 한 요청만 보낸다.
    if (busy) return
    setBusy(true)
    setFailure(null)
    try {
      // E02는 이미 성공했고 확인만 못 한 경우에는 E02를 다시 보내지 않고 E03만 다시 읽는다.
      if (failure !== 'unconfirmed') await logout()
    } catch {
      setFailure('failed')
      setBusy(false)
      return
    }
    const check = await checkLoggedOut()
    if (check === 'logged_out') {
      // 방문자로 확인된 뒤에 전역 상태를 갱신하고 이동한다.
      await refresh()
      setOpen(false)
      navigate(userPaths.noteList, { replace: true })
      return
    }
    setFailure(check === 'unknown' ? 'unconfirmed' : 'failed')
    setBusy(false)
  }

  return (
    <div ref={rootRef} className={styles.root}>
      <IconButton
        ref={triggerRef}
        label={open ? '내 계정 메뉴 닫기' : '내 계정'}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cx(open && styles.open)}
        onClick={() => setOpen((value) => !value)}
      >
        <AccountIcon />
      </IconButton>
      {open ? (
        <div ref={menuRef} role="menu" aria-label="내 계정" className={styles.menu} onKeyDown={handleKeyDown}>
          {/* 어디서 열었는지 넘겨, 내 정보의 "돌아가기"가 그 화면으로 돌아가게 한다 */}
          <Link role="menuitem" tabIndex={-1} to={userPaths.myInfo} state={{ from: location.pathname }} className={styles.item} onClick={() => setOpen(false)}>
            내 정보
          </Link>
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            aria-disabled={busy ? 'true' : undefined}
            className={styles.item}
            onClick={handleLogout}
          >
            {failure === 'unconfirmed' ? MESSAGES.recheck : MESSAGES.logout}
          </button>
          {failure ? (
            <p role="alert" className={styles.failed}>
              {MESSAGES[failure]}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
