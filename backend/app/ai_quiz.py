"""퀴즈 생성 응답의 구조 검증 (MEG-86, API spec v0.2 5.2·5.6).

모델이 돌려준 JSON 텍스트를 문항 목록으로 바꾼다. 구조가 깨졌으면 불완전 응답과 같게 502로 끝낸다(1.4.4).
이 검사는 원장 정산 뒤에 한다. 응답은 받았으므로 비용은 usage로 이미 정산돼 있다.
"""

import json
import re
from dataclasses import dataclass

from app.bedrock import AiCallError

DIFFICULTIES = ("상", "중", "하")
QUIZ_FIELDS = ("question", "answer", "explanation", "difficulty")

# 모델이 JSON을 코드 블록(```json, ```JSON, 언어 표시 없음 등)으로 감싸 보내는 경우만 벗긴다.
_FENCE = re.compile(r"\A```[A-Za-z]*[ \t]*\n(?P<body>.*)\n```\s*\Z", re.DOTALL)


@dataclass(frozen=True)
class QuizItemDraft:
    question: str
    answer: str
    explanation: str
    difficulty: str


def _invalid() -> AiCallError:
    # 응답 원문은 담지 않는다.
    return AiCallError("response", "InvalidQuizJson")


def parse_quiz_items(text: str, expected_count: int | None = None, numbered: bool = False) -> list[QuizItemDraft]:
    """[{question, answer, explanation, difficulty}, ...] 또는 {"items": [...]}를 받는다.

    네 필드는 모두 비어 있지 않은 문자열이어야 하고 difficulty는 상·중·하만 받는다. 다른 키는 버린다.
    expected_count를 주면 문항 수가 같아야 한다.
    numbered가 True면 각 원소에 자료 번호 n(1부터 빠짐·중복 없이)이 있어야 하고, 결과는 n 순서로 돌려준다.
    모델이 문항 순서를 바꿔 내도 문항이 다른 용어에 붙지 않게 하려는 것이다(E11).
    """
    body = text.replace("\r\n", "\n").strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group("body").strip()
    try:
        data = json.loads(body)
    except ValueError:
        raise _invalid() from None

    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list) or not data:
        raise _invalid()
    if expected_count is not None and len(data) != expected_count:
        raise _invalid()

    items = []
    numbers = []
    for entry in data:
        if not isinstance(entry, dict):
            raise _invalid()
        if numbered:
            number = entry.get("n")
            if not isinstance(number, int) or isinstance(number, bool):
                raise _invalid()
            numbers.append(number)
        values = {}
        for field in QUIZ_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise _invalid()
            values[field] = value.strip()
        if values["difficulty"] not in DIFFICULTIES:
            raise _invalid()
        items.append(QuizItemDraft(**values))
    if numbered:
        if sorted(numbers) != list(range(1, len(items) + 1)):
            raise _invalid()
        items = [item for _, item in sorted(zip(numbers, items), key=lambda pair: pair[0])]
    return items
