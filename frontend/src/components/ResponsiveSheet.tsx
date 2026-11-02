import type { ReactNode } from 'react'
import { BottomSheet } from './BottomSheet.tsx'
import { SidePanel } from './SidePanel.tsx'
import { useWideLayout } from './useWideLayout.ts'

type ResponsiveSheetProps = {
  open: boolean
  onClose: () => void
  title: ReactNode
  badge?: ReactNode
  closeLabel?: string
  children: ReactNode
  // PC 폭에서 용어 링크가 aria-controls로 가리킬 패널 id
  panelId?: string
  // PC 패널을 닫을 때 포커스를 돌려줄 요소(예: 마지막으로 누른 용어 링크)
  returnFocus?: () => HTMLElement | null
  // false면 PC 폭에서도 바텀시트를 쓴다(PC 패널로 바꾸기로 한 안내만 true로 둔다)
  allowPanel?: boolean
}

// 폭에 따라 시트를 고른다. 1024px 이상이면 오른쪽 사이드 패널(SidePanel), 미만이면 기존 바텀시트(BottomSheet)다.
// 열림 상태는 부모가 계속 가지므로 창 크기를 바꿔도 열려 있던 것은 열린 채 모양만 바뀐다(안쪽 내용은 새로 그려진다).
export function ResponsiveSheet({ panelId, returnFocus, allowPanel = true, ...sheet }: ResponsiveSheetProps) {
  const wide = useWideLayout()
  return wide && allowPanel ? <SidePanel id={panelId} returnFocus={returnFocus} {...sheet} /> : <BottomSheet {...sheet} />
}
