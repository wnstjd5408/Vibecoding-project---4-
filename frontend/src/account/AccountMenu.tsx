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
import { confirmLogout, logout } from './logout.ts'
import styles from './AccountMenu.module.css'

// 로그아웃 실패 안내. 목업에 화면이 없어 임시 문구다(문구 미정, 확정되면 이 한 곳만 고친다).
const LOGOUT_FAILED = '로그아웃하지 못했어요. 잠시 뒤에 다시 시도해 주세요.'

export function AccountMenu() {
  const navigate = useNavigate()
  const location = useLocation()
  const { refresh } = useAuth()
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

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
    setFailed(false)
    try {
      await logout()
      // E03으로 방문자 상태를 확인한 뒤에만 이동한다. 확인하지 못하면 로그아웃이 끝났다고 알리지 않는다.
      if (await confirmLogout(refresh)) {
        setOpen(false)
        navigate(userPaths.noteList, { replace: true })
        return
      }
      setFailed(true)
    } catch {
      setFailed(true)
    }
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
            로그아웃
          </button>
          {failed ? (
            <p role="alert" className={styles.failed}>
              {LOGOUT_FAILED}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
