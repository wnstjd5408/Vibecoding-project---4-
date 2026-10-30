import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation } from 'react-router'
import { BottomSheet } from '../components/BottomSheet.tsx'
import { LinkButton } from '../components/Button.tsx'
import { userPaths } from '../routes/paths.ts'
import { isLoginRequired } from './isLoginRequired.ts'
import { LoginPromptContext } from './loginPromptContext.ts'
import type { LoginPromptContextValue, LoginPromptOptions } from './loginPromptContext.ts'
import { LOGIN_PROMPT_MESSAGES } from './messages.ts'
import styles from './LoginPromptProvider.module.css'

// 앱 위쪽에 하나 둔다. 방문자가 로그인 기능을 눌렀을 때 뜨는 안내 시트(F1-1c·F2-2b)를 그린다.
// 시트는 기존 BottomSheet를 그대로 쓴다. 제목 포커스, Esc·닫기·막 누르기, 연 요소로의 포커스 복귀는 BottomSheet가 맡는다.
export function LoginPromptProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState<string>(LOGIN_PROMPT_MESSAGES.body)
  const { pathname } = useLocation()

  // 화면을 옮기면(로그인 버튼, 뒤로·앞으로 가기 등) 열림 상태 자체를 해제한다. 시트는 앱 위쪽에 있어 화면이 바뀌어도 남기 때문이다.
  // 숨기기만 하면 원래 경로로 돌아왔을 때 닫힌 시트가 되살아난다. 렌더 중에 경로 변화를 알아채 상태를 바꾸는 것이 React가 권하는 방식이다.
  const [shownAt, setShownAt] = useState(pathname)
  if (shownAt !== pathname) {
    setShownAt(pathname)
    setOpen(false)
  }

  const openLoginPrompt = useCallback((options?: LoginPromptOptions) => {
    // 호출마다 본문을 새로 정한다. 퀴즈 문구로 열었다 닫은 뒤 기본 호출을 해도 이전 문구가 남지 않는다.
    setBody(options?.body ?? LOGIN_PROMPT_MESSAGES.body)
    setOpen(true)
  }, [])

  const handleLoginRequired = useCallback((error: unknown, options?: LoginPromptOptions) => {
    if (!isLoginRequired(error)) return false
    openLoginPrompt(options)
    return true
  }, [openLoginPrompt])

  const value = useMemo<LoginPromptContextValue>(() => ({ openLoginPrompt, handleLoginRequired }), [openLoginPrompt, handleLoginRequired])

  return (
    <LoginPromptContext.Provider value={value}>
      {children}
      <BottomSheet open={open} onClose={() => setOpen(false)} title={LOGIN_PROMPT_MESSAGES.title}>
        <p className={styles.body}>{body}</p>
        <div className={styles.actions}>
          <LinkButton variant="primary" to={userPaths.login} onClick={() => setOpen(false)}>{LOGIN_PROMPT_MESSAGES.login}</LinkButton>
        </div>
      </BottomSheet>
    </LoginPromptContext.Provider>
  )
}
