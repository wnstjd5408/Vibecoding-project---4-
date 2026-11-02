"""Independent teaching demonstrations; never evaluation reference answers.

Reviewed source: Python tutorial /datastructures.html#using-lists-as-stacks
(2026-11-02).
Examples are authored paraphrases; scenarios are explicitly hypothetical.
"""
import json

EXAMPLES = (
    ({"term": "스택", "context": "마지막에 넣은 항목을 먼저 꺼낸다.",
      "sources": {"1": "스택은 LIFO(후입선출)이다. Python 리스트에서는 append로 끝에 추가하고 인자 없는 pop으로 마지막 항목을 꺼낸다. 빈 리스트의 pop은 IndexError다.",
                  "2": "가상 편집기 예시: 작업 A 뒤에 B를 기록했다. 최근 작업부터 취소하려면 B, A 순으로 기록을 꺼내고 각각의 역작업을 실행한다. 스택은 기록 순서를 제공하며 역작업은 앱이 구현해야 한다."}},
     {"summary": ["스택은 마지막에 넣은 항목을 먼저 꺼내는 자료구조입니다.[1]", "최근 작업부터 되짚는 순서를 표현할 수 있습니다.[2]", "기록을 꺼내는 것과 실제 작업을 취소하는 것은 다릅니다.[2]"],
      "explanation": "**정의**\n스택은 나중에 넣은 항목을 먼저 꺼내는 후입선출(LIFO) 자료구조입니다.[1]\n**작동 원리**\nPython 리스트의 append는 끝에 추가하고, 인자 없는 pop은 마지막 항목을 꺼냅니다.[1]\n**활용 예시**\n편집기에서 A 다음 B 작업을 했다고 가정해 봅시다. 최근 작업부터 취소해야 하므로 기록을 스택에 넣고 B, A 순으로 꺼냅니다. 실제 취소는 앱이 각 기록의 역작업을 실행해야 합니다.[2]\n**주의사항**\n빈 Python 리스트에서 pop을 호출하면 IndexError가 발생합니다. 꺼낼 항목이 있는지 확인해야 합니다.[1]",
      "source_ids": ["1", "2"]}),

)


def example_messages():
    """Return fresh messages; caller mutation cannot alter later requests."""
    return [{"role": role, "content": [{"text": json.dumps(value, ensure_ascii=False)}]}
            for pair in EXAMPLES for role, value in zip(("user", "assistant"), pair)]
