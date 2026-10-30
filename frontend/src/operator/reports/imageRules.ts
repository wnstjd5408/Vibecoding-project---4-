// 사전 이미지 올리기 규칙(MEG-84 F5-3). 티켓이 정한 값이다: png·jpeg·webp, 4MB 이하.
// 용어 사전 화면(MEG-82)에도 같은 규칙이 있다. 두 브랜치가 따로라 지금은 각자 두고, 둘 다 머지된 뒤 하나로 합친다.
export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'] as const
export const IMAGE_MAX_BYTES = 4 * 1024 * 1024

// 안내 문구(문구는 목업의 형식을 따르고 용량만 티켓 값이다)
export const IMAGE_REJECTED_MESSAGE = '4MB 이하의 PNG, JPG, WebP 이미지를 선택해 주세요.'

// 올릴 수 있는 파일이면 true
export function isAllowedImage(file: Pick<File, 'type' | 'size'>): boolean {
  return (IMAGE_TYPES as readonly string[]).includes(file.type) && file.size <= IMAGE_MAX_BYTES
}
