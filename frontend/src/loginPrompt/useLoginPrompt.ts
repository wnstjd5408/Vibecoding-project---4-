import { useContext } from 'react'
import { LoginPromptContext } from './loginPromptContext.ts'
import type { LoginPromptContextValue } from './loginPromptContext.ts'

// 로그인 안내 시트를 화면이 명시적으로 부른다. apiFetch가 알아서 열지 않는다.
//   const { handleLoginRequired } = useLoginPrompt()
//   try { await apiFetch(...) } catch (error) { if (!handleLoginRequired(error)) showError() }
export function useLoginPrompt(): LoginPromptContextValue {
  const value = useContext(LoginPromptContext)
  if (!value) throw new Error('useLoginPrompt는 LoginPromptProvider 안에서만 쓸 수 있다')
  return value
}
