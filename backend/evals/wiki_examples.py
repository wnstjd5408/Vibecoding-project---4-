"""Independent teaching demonstrations; never evaluation reference answers.

Reviewed source: Python tutorial /datastructures.html#using-lists-as-stacks
(2026-11-02).
Examples are authored paraphrases; scenarios are explicitly hypothetical.
"""
import json

EXAMPLES = (
    ({"term": "스택", "context": "마지막에 넣은 항목을 먼저 꺼낸다.",
      "sources": {"1": "스택은 LIFO(후입선출)이다. Python 리스트에서는 append로 끝에 추가하고 인자 없는 pop으로 마지막 항목을 꺼낸다. 빈 리스트의 pop은 IndexError다.",
                  "2": "스택에 저장한 작업 기록은 최근 기록부터 꺼낼 수 있다. 기록을 꺼내는 것만으로 실행된 작업이 취소되지는 않는다. 취소 기능에는 해당 작업을 되돌리는 별도 동작이 필요하다."}},
     {"summary": ["스택은 마지막에 넣은 항목을 먼저 꺼내는 자료구조입니다.[1]", "최근 작업부터 되짚는 순서를 표현할 수 있습니다.[2]", "기록을 꺼내는 것과 실제 작업을 취소하는 것은 다릅니다.[2]"],
      "explanation": "**정의**\n스택은 나중에 넣은 항목을 먼저 꺼내는 후입선출(LIFO) 자료구조입니다.[1]\n**작동 원리**\n일반적으로 한쪽 끝에 항목을 넣고 같은 끝에서 꺼내므로 마지막 항목부터 나옵니다.[1] Python 리스트에서는 append로 끝에 추가하고, 위치를 따로 지정하지 않은 pop으로 마지막 항목을 꺼냅니다.[1]\n**활용 예시**\n가령 편집기 사용자가 제목을 고친 뒤 본문을 삭제했다고 가정해 봅시다. 제목은 유지하고 마지막 본문 삭제만 취소하려면 최근 작업 기록부터 찾아야 합니다. 두 작업의 기록을 스택에 넣으면 본문 삭제 기록을 먼저 꺼내 삭제를 되돌리는 동작에 사용할 수 있습니다.[1][2] 실제 본문 복구는 앱이 삭제를 되돌리는 동작을 구현해야 합니다.[2]\n**주의사항**\n빈 Python 리스트에서 pop을 호출하면 꺼낼 항목이 없다는 오류인 IndexError가 발생합니다. 꺼낼 항목이 있는지 확인해야 합니다.[1]",
      "source_ids": ["1", "2"]}),

)


def example_messages():
    """Return fresh messages; caller mutation cannot alter later requests."""
    return [{"role": role, "content": [{"text": json.dumps(value, ensure_ascii=False)}]}
            for pair in EXAMPLES for role, value in zip(("user", "assistant"), pair)]
