import { IconButton } from './IconButton.tsx'
import { StarIcon } from './icons.tsx'

type FavoriteToggleProps = {
  // 즐겨찾기한 상태인지. 켜지면 별이 채워지고 aria-pressed가 true가 된다.
  pressed: boolean
  onPressedChange: (pressed: boolean) => void
  label?: string
  disabled?: boolean
}

// 즐겨찾기 켜기·끄기. 켜진 상태는 별 모양과 aria-pressed로 함께 알린다.
export function FavoriteToggle({ pressed, onPressedChange, label = '즐겨찾기', disabled }: FavoriteToggleProps) {
  return (
    <IconButton label={label} aria-pressed={pressed} disabled={disabled} onClick={() => onPressedChange(!pressed)}>
      <StarIcon filled={pressed} />
    </IconButton>
  )
}
