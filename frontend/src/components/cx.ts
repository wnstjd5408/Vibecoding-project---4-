// CSS 클래스 이름을 이어 붙인다. 비어 있는 값(false·undefined)은 건너뛴다.
export function cx(...names: (string | false | undefined)[]): string {
  return names.filter(Boolean).join(' ')
}
