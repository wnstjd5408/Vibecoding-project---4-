"""Independent teaching demonstrations; never evaluation reference answers.

Reviewed sources: Python tutorial /datastructures.html#using-lists-as-stacks,
PostgreSQL 18 /docs/18/tutorial-transactions.html (2026-11-02).
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
    ({"term": "데이터베이스 트랜잭션", "context": "여러 DB 변경을 하나의 단위로 묶는다.",
      "sources": {"1": "트랜잭션은 여러 DB 변경을 전부 반영하거나 전부 취소하는 단위다. PostgreSQL에서 BEGIN으로 시작하고 COMMIT으로 확정하며 ROLLBACK으로 해당 트랜잭션의 변경을 취소한다.",
                  "2": "단순화한 이체 예시: A 계좌 차감과 B 계좌 증가가 따로 확정되면 한쪽만 반영될 수 있다. 두 변경을 같은 트랜잭션으로 묶는다. 잔액 부족을 발견하면 COMMIT 대신 ROLLBACK할 수 있다."}},
     {"summary": ["트랜잭션은 여러 DB 변경을 하나의 처리 단위로 묶습니다.[1]", "묶인 변경은 전부 반영하거나 전부 취소합니다.[1]", "함께 처리할 변경을 같은 트랜잭션에 포함해야 합니다.[2]"],
      "explanation": "**정의**\n트랜잭션은 여러 DB 변경을 전부 반영하거나 전부 취소하는 처리 단위입니다. 이런 성질을 원자성이라고 합니다.[1]\n**작동 원리**\nPostgreSQL에서는 BEGIN으로 시작하고 COMMIT으로 변경을 확정합니다. 확정하지 않으려면 ROLLBACK으로 해당 변경을 취소합니다.[1]\n**활용 예시**\nA에서 B로 이체한다고 가정해 봅시다. 차감만 확정되면 돈이 빠졌는데 B에는 들어오지 않는 문제가 생깁니다. 두 변경을 같은 트랜잭션에 묶고, 잔액 부족을 발견하면 확정 대신 취소합니다.[2]\n**주의사항**\n차감과 증가를 따로 확정하면 두 변경을 한 단위로 보호하지 못합니다. 함께 처리할 변경이 같은 트랜잭션에 들어 있는지 확인해야 합니다.[2]",
      "source_ids": ["1", "2"]}),
)


def example_messages():
    """Return fresh messages; caller mutation cannot alter later requests."""
    return [{"role": role, "content": [{"text": json.dumps(value, ensure_ascii=False)}]}
            for pair in EXAMPLES for role, value in zip(("user", "assistant"), pair)]
