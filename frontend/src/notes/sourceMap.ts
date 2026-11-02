// 노트 본문(body_markdown) 원문 위치 계산. 화면과 분리한 순수 함수만 둔다(MEG-74, Q-N3).
// 위치는 모두 JavaScript 문자열(UTF-16 코드 유닛) 기준이다. 서버의 glossary_spans는 유니코드 코드포인트 기준이라 toUtf16Index로 바꿔 쓴다.

// 코드포인트 위치를 UTF-16 위치로 바꾼다. 범위를 벗어나면 null이다. 코드포인트 수와 같은 값(문자열 끝)은 허용한다.
export function toUtf16Index(text: string, codePointIndex: number): number | null {
  if (!Number.isInteger(codePointIndex) || codePointIndex < 0) return null
  let utf16 = 0
  let count = 0
  for (const char of text) {
    if (count === codePointIndex) return utf16
    utf16 += char.length
    count += 1
  }
  return count === codePointIndex ? utf16 : null
}

// 렌더 글자 한 덩어리가 원문의 어디서 왔는지.
//  - exact: 글자가 원문과 같다. 덩어리 안 위치가 원문 위치와 1:1이라 글자 단위로 계산한다.
//  - 그 밖(exact가 false): 이스케이프·엔티티처럼 글자 수가 달라 한 덩어리로만 대응한다. 선택 끝점은 덩어리 경계로 밀어낸다.
export type Piece = { text: string; srcStart: number; srcEnd: number; exact: boolean }

const NAMED_ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }

// 원문 조각(source) 속 엔티티 하나를 읽는다. 지원하는 것은 숫자 엔티티와 NAMED_ENTITIES뿐이다. 아니면 null이다.
function readEntity(source: string, at: number): { decoded: string; length: number } | null {
  const end = source.indexOf(';', at)
  if (end < 0 || end - at > 12) return null
  const name = source.slice(at + 1, end)
  const numeric = /^#(?:[xX]([0-9a-fA-F]{1,6})|([0-9]{1,7}))$/.exec(name)
  if (numeric) {
    const code = numeric[1] ? parseInt(numeric[1], 16) : parseInt(numeric[2], 10)
    if (code === 0 || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return null
    return { decoded: String.fromCodePoint(code), length: end - at + 1 }
  }
  const decoded = NAMED_ENTITIES[name]
  return decoded === undefined ? null : { decoded, length: end - at + 1 }
}

// 파서가 준 글자(value)와 원문 조각(source, 문서 안 시작 위치 sourceStart)을 맞춰 본다.
// 맞출 수 없으면 null이다. 이 경우 호출한 쪽은 그 글자를 위치 계산 불가로 둔다(임의로 추정하지 않는다).
// 다루는 차이: 백슬래시 이스케이프, 숫자·기본 이름 엔티티, 줄 바꿈 뒤 들여쓰기, 줄 끝 공백.
export function alignText(value: string, source: string, sourceStart: number): Piece[] | null {
  const pieces: Piece[] = []
  let i = 0
  let j = 0
  const pushExact = (length: number) => {
    const last = pieces[pieces.length - 1]
    const text = value.slice(i, i + length)
    if (last?.exact && last.srcEnd === sourceStart + j) {
      last.text += text
      last.srcEnd += length
    } else pieces.push({ text, srcStart: sourceStart + j, srcEnd: sourceStart + j + length, exact: true })
    i += length
    j += length
  }
  while (i < value.length || j < source.length) {
    const v = value[i]
    const s = source[j]
    if (s === undefined) return null
    if (s === '\\' && v !== undefined && source[j + 1] === v) {
      pieces.push({ text: v, srcStart: sourceStart + j, srcEnd: sourceStart + j + 2, exact: false })
      i += 1
      j += 2
      continue
    }
    if (s === '&' && v !== undefined) {
      const entity = readEntity(source, j)
      if (entity && value.startsWith(entity.decoded, i)) {
        pieces.push({ text: entity.decoded, srcStart: sourceStart + j, srcEnd: sourceStart + j + entity.length, exact: false })
        i += entity.decoded.length
        j += entity.length
        continue
      }
    }
    // 글자가 같으면 그대로 대응한다. 엔티티가 아닌 `&`(예: AT&T)도 여기서 맞는다.
    if (v !== undefined && v === s) {
      pushExact(1)
      continue
    }
    // 파서가 버린 공백: 줄 바꿈 바로 뒤 들여쓰기, 줄 끝 공백
    if ((s === ' ' || s === '\t') && (value[i - 1] === '\n' || v === '\n' || v === undefined)) {
      j += 1
      continue
    }
    return null
  }
  return pieces
}
