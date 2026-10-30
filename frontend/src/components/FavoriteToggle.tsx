import type { ComponentPropsWithRef } from 'react'
import { Button } from './Button.tsx'
import { StarIcon } from './icons.tsx'

type FavoriteToggleProps = {
  // 즐겨찾기한 상태인지. 켜지면 먹색으로 채우고 aria-pressed가 true가 된다.
  pressed: boolean
  onPressedChange: (pressed: boolean) => void
} & Omit<ComponentPropsWithRef<'button'>, 'children' | 'onClick' | 'type'>

// 즐겨찾기 켜기·끄기. 별 모양만 쓰지 않고 글자 라벨을 함께 보인다(꺼짐 "즐겨찾기" 보조 버튼, 켜짐 "즐겨찾기함" 채움 버튼).
export function FavoriteToggle({ pressed, onPressedChange, ...rest }: FavoriteToggleProps) {
  return (
    <Button variant={pressed ? 'primary' : 'outline'} aria-pressed={pressed} onClick={() => onPressedChange(!pressed)} {...rest}>
      <StarIcon filled={pressed} />
      {pressed ? '즐겨찾기함' : '즐겨찾기'}
    </Button>
  )
}
