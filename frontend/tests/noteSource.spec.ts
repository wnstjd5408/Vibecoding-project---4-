import { expect, test } from '@playwright/test'
import { alignText, toUtf16Index } from '../src/notes/sourceMap.ts'
import { prepareSpans, splitBySpans } from '../src/notes/spans.ts'

// MEG-74 위치 계산 순수 함수(브라우저 없이). 합성 문자열만 쓴다.

test('코드포인트 위치를 UTF-16 위치로 바꾼다(이모지는 두 칸)', () => {
  const text = '😀a𠮷b'
  expect(toUtf16Index(text, 0)).toBe(0)
  expect(toUtf16Index(text, 1)).toBe(2) // 😀 뒤
  expect(toUtf16Index(text, 2)).toBe(3) // a 뒤
  expect(toUtf16Index(text, 3)).toBe(5) // 𠮷 뒤
  expect(toUtf16Index(text, 4)).toBe(6) // 끝(코드포인트 수와 같은 값)
  expect(toUtf16Index(text, 5)).toBeNull()
  expect(toUtf16Index(text, -1)).toBeNull()
  expect(toUtf16Index(text, 1.5)).toBeNull()
})

test('API spec 예시 1의 위치(6, 17)는 ExampleTerm을 가리킨다', () => {
  const body = '이 노트는 ExampleTerm 을 설명합니다. UnknownWord 는 사전에 없습니다.'
  const [span] = prepareSpans(body, [{ term_id: 7, start: 6, end: 17 }])
  expect(body.slice(span.start, span.end)).toBe('ExampleTerm')
})

test('이모지가 앞에 있어도 코드포인트 위치가 맞는 글자를 가리킨다', () => {
  const body = '😀 ExampleTerm'
  const [span] = prepareSpans(body, [{ term_id: 7, start: 2, end: 13 }])
  expect(body.slice(span.start, span.end)).toBe('ExampleTerm')
})

test('범위 밖·빈 범위·겹치는 용어는 버린다', () => {
  const body = 'abcdef'
  const spans = prepareSpans(body, [
    { term_id: 1, start: 0, end: 3 },
    { term_id: 2, start: 2, end: 4 }, // 앞 용어와 겹침
    { term_id: 3, start: 4, end: 4 }, // 빔
    { term_id: 4, start: 5, end: 9 }, // 범위 밖
    { term_id: 5, start: 3, end: 6 },
  ])
  expect(spans.map((span) => span.termId)).toEqual([1, 5])
})

test('글자가 원문과 같은 본문은 글자 단위로 대응한다', () => {
  expect(alignText('굵은 ExampleTerm', '굵은 ExampleTerm', 4)).toEqual([
    { text: '굵은 ExampleTerm', srcStart: 4, srcEnd: 18, exact: true },
  ])
})

test('백슬래시 이스케이프는 두 칸을 한 글자로 대응한다', () => {
  const source = '별표 \\*는 \\_밑줄\\_'
  const value = '별표 *는 _밑줄_'
  const pieces = alignText(value, source, 10)
  expect(pieces?.map((piece) => piece.text).join('')).toBe(value)
  expect(pieces?.filter((piece) => !piece.exact).map((piece) => [piece.text, piece.srcEnd - piece.srcStart])).toEqual([['*', 2], ['_', 2], ['_', 2]])
  // 이스케이프 조각의 원문 범위가 실제 원문 `\*`를 가리킨다
  const star = pieces?.find((piece) => piece.text === '*')
  expect(source.slice((star?.srcStart ?? 0) - 10, (star?.srcEnd ?? 0) - 10)).toBe('\\*')
})

test('숫자 엔티티와 기본 이름 엔티티를 읽고, 모르는 이름 엔티티는 계산하지 않는다', () => {
  const known = alignText('& <b> #', '&amp; &lt;b&gt; &#35;', 0)
  expect(known?.map((piece) => piece.text).join('')).toBe('& <b> #')
  expect(known?.filter((piece) => !piece.exact)).toHaveLength(4)
  expect(alignText('é', '&eacute;', 0)).toBeNull()
})

test('줄 바꿈 뒤 들여쓰기와 줄 끝 공백은 건너뛴다', () => {
  const source = '첫 줄\n  둘째 줄\n셋째 줄 \n넷째'
  const pieces = alignText('첫 줄\n둘째 줄\n셋째 줄\n넷째', source, 0)
  expect(pieces).not.toBeNull()
  // 원문에서 "둘째"가 시작하는 위치가 조각에 그대로 남는다
  const second = pieces?.find((piece) => piece.text.includes('둘째'))
  expect(second && source.indexOf('둘째') - second.srcStart).toBeGreaterThanOrEqual(0)
  expect(source.slice(second?.srcStart ?? 0, second?.srcEnd ?? 0)).toContain('둘째')
})

test('맞출 수 없는 글자는 추정하지 않고 null이다', () => {
  expect(alignText('abc', 'abd', 0)).toBeNull()
  expect(alignText('abc', 'ab', 0)).toBeNull()
})

test('용어 경계에서 같은 글자 조각은 글자 단위로, 다른 조각은 통째로 자른다', () => {
  const pieces = alignText('가나다라', '가나다라', 10) ?? []
  const spans = [{ termId: 7, start: 11, end: 13 }]
  expect(splitBySpans(pieces, spans)).toEqual([
    { text: '가', srcStart: 10, srcEnd: 11, exact: true },
    { text: '나다', srcStart: 11, srcEnd: 13, exact: true, termId: 7 },
    { text: '라', srcStart: 13, srcEnd: 14, exact: true },
  ])
  const escaped = alignText('*', '\\*', 0) ?? []
  expect(splitBySpans(escaped, [{ termId: 7, start: 1, end: 2 }])).toEqual([{ text: '*', srcStart: 0, srcEnd: 2, exact: false, termId: 7 }])
})
