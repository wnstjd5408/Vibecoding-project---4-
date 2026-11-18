"""CS Agent 노트 임시 검색의 문단 분할·전처리·선택 문맥 제외·키워드 검색 (MEG-237 AC-4, 기술 검토 v0.4 4절).

DB와 모델 없이 도는 단위 시험이다. 데이터는 모두 합성이다. 공개 노트만 읽는지(AC-1)는 test_agent_sources.py가
E29를 거쳐 보고, 실제 래퍼의 is_published 필터는 test_supabase_agent_client.py가 본다.
"""

import pytest

from app.agent_note_search import (
    MAX_CHUNK_CHARS,
    MAX_RESULTS,
    NoteRetriever,
    keywords,
    note_chunks,
    replace_images,
    search_notes,
)
from app.agent_output import usable_paragraphs
from app.agent_retrieval import RetrievalContext
from app.auth import SessionUser


def context(**overrides) -> RetrievalContext:
    values = {"conversation_id": "c", "origin": "note", "note_id": 1, "topic_label": "", **overrides}
    return RetrievalContext(**values)


def note(note_id: int, body: str, title: str = "합성 노트", revision: int = 3) -> dict:
    return {"id": note_id, "revision": revision, "title": title, "body_markdown": body}


# --- 문단 분할 ---


def test_sections_are_split_by_heading_and_keep_the_heading_as_section():
    body = "머리말 문장.\n\n# 정의\n멱등성은 같은 결과를 낸다.\n\n## 재시도 ##\n재시도는 안전하다.\n"
    assert [(c.section, c.text) for c in note_chunks(body)] == [
        (None, "머리말 문장."),
        ("정의", "멱등성은 같은 결과를 낸다."),
        ("재시도", "재시도는 안전하다."),
    ]


def test_a_section_over_the_limit_is_split_at_paragraph_boundaries_without_cutting():
    paragraphs = [f"{n}번 단락 " + "가" * 590 for n in range(1, 6)]  # 단락마다 약 597자
    body = "# 긴 절\n" + "\n\n".join(paragraphs)
    chunks = note_chunks(body)
    assert len(chunks) > 1 and all(c.section == "긴 절" for c in chunks)
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
    # 자르지 않는다: 단락이 모두 온전히, 순서대로 남는다.
    rebuilt = [p for c in chunks for p in c.text.split("\n\n")]
    assert rebuilt == paragraphs
    # 저장 전 거르기(usable_paragraphs)에서도 잘리지 않는다.
    found = search_notes([note(1, body)], "단락", context())
    assert found and usable_paragraphs(found) == found


def test_a_single_paragraph_over_the_limit_is_split_at_line_boundaries():
    lines = [f"줄 {n} " + "나" * 300 for n in range(8)]
    chunks = note_chunks("# 절\n" + "\n".join(lines))
    assert len(chunks) > 1 and all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
    assert [line for c in chunks for line in c.text.split("\n")] == lines


def test_a_single_line_over_the_limit_is_split_by_length():
    chunks = note_chunks("다" * (MAX_CHUNK_CHARS * 2 + 10))
    assert [len(c.text) for c in chunks] == [MAX_CHUNK_CHARS, MAX_CHUNK_CHARS, 10]


def test_headings_and_blank_lines_inside_code_blocks_are_not_boundaries():
    body = "# 코드\n설명.\n\n```python\n# 주석\n\nx = 1\n```\n\n```mermaid\nflowchart LR\n\n  A --> B\n```"
    chunks = note_chunks(body)
    assert [c.section for c in chunks] == ["코드"]
    assert "```python\n# 주석\n\nx = 1\n```" in chunks[0].text
    assert "```mermaid\nflowchart LR\n\n  A --> B\n```" in chunks[0].text


def test_splitting_is_deterministic_and_ignores_carriage_returns():
    body = "# 정의\r\n멱등성 문단.\r\n\r\n둘째 단락."
    assert note_chunks(body) == note_chunks(body.replace("\r\n", "\n")) == note_chunks(body.replace("\r\n", "\n"))


def test_empty_sections_and_blank_bodies_make_no_chunks():
    assert note_chunks("") == []
    assert note_chunks("# 빈 절\n\n\n# 또 빈 절\n") == []


# --- 전처리 ---


def test_image_syntax_becomes_alt_text_and_code_is_kept():
    text = "앞 ![구조 그림](note-image:abc) 뒤 ![](note-image:b2)\n\n```\n![x](note-image:keep)\n```\n`![y](note-image:inline)`"
    replaced = replace_images(text)
    assert replaced.startswith("앞 [그림: 구조 그림] 뒤 [그림]")
    assert "![x](note-image:keep)" in replaced and "`![y](note-image:inline)`" in replaced


def test_multiline_alt_text_is_folded_and_bare_tokens_are_removed():
    assert replace_images("![여러\n줄 설명](note-image:a1) 그리고 note-image:zz 끝") == "[그림: 여러 줄 설명] 그리고  끝"


def test_chunks_carry_the_replaced_text():
    [chunk] = note_chunks("# 절\n그림 ![흐름도](note-image:k1) 설명")
    assert chunk.text == "그림 [그림: 흐름도] 설명" and "note-image:" not in chunk.text


# --- 키워드 ---


def test_keywords_strip_particles_and_skip_common_words():
    assert keywords("멱등성이란 뭐야? HTTP 재시도는 어떻게 동작해?") == ["멱등성", "http", "재시도", "동작"]
    assert keywords("방금 설명을 더 자세히 설명해 주세요.") == []
    # 떼고 남는 말이 1글자면 떼지 않는다.
    assert keywords("차이") == ["차이"]


# --- 검색과 선택 문맥 제외 ---


NOTES = [
    note(1, "# 정의\n멱등성은 같은 요청을 여러 번 보내도 결과가 같다.\n\n# 예시\nPUT은 멱등하고 POST는 아니다.", "HTTP 노트"),
    note(2, "# 재시도\n재시도는 멱등성이 있는 요청에만 안전하다.", "재시도 노트"),
    note(3, "# 무관\n스레드는 프로세스 안의 실행 단위다.", "운영체제"),
]


def test_only_paragraphs_with_question_keywords_are_returned_in_score_order():
    found = search_notes(NOTES, "멱등성이 뭐야?", context())
    assert [(p.source_id, p.section) for p in found] == [("1", "정의"), ("2", "재시도")]
    first = found[0]
    assert (first.source_kind, first.revision, first.title) == ("note", "3", "HTTP 노트")


def test_a_paragraph_holding_the_selection_is_excluded_but_other_paragraphs_of_that_note_stay():
    selected = "멱등성은 같은 요청을 여러 번 보내도"
    query = context(selection_note_ids=(1,), selection_texts=(selected,))
    assert ("1", "정의") in [(p.source_id, p.section) for p in search_notes(NOTES, "멱등 PUT", context())]
    # 선택 문장이 든 문단(1번 노트 정의)만 빠진다. 같은 노트의 다른 문단과 다른 노트는 근거로 쓴다.
    found = search_notes(NOTES, "멱등 PUT", query)
    assert [(p.source_id, p.section) for p in found] == [("1", "예시"), ("2", "재시도")]


def test_the_same_text_in_another_note_is_not_excluded():
    selected = "멱등성"
    found = search_notes(NOTES, "멱등성", context(selection_note_ids=(1,), selection_texts=(selected,)))
    assert [p.source_id for p in found] == ["2"]


def test_a_selection_spanning_paragraphs_excludes_each_paragraph_it_covers():
    selected = "멱등성은 같은 요청을 여러 번 보내도 결과가 같다.\n\n# 예시\nPUT은 멱등하고 POST는 아니다."
    found = search_notes(NOTES, "멱등성 PUT", context(selection_note_ids=(1,), selection_texts=(selected,)))
    assert all(p.source_id != "1" for p in found)


def test_a_selection_with_an_image_matches_the_replaced_paragraph():
    notes = [note(5, "# 그림\n흐름 ![도식](note-image:k) 멱등성 설명 문장")]
    found = search_notes(
        notes, "멱등성", context(selection_note_ids=(5,), selection_texts=("흐름 ![도식](note-image:k) 멱등성",))
    )
    assert found == []


def test_context_words_only_reorder_and_are_used_when_the_question_has_none():
    # 질문 낱말이 없으면(빠른 질문 칩) 주제·직전 질문 낱말로 찾는다.
    found = search_notes(NOTES, "방금 설명을 더 쉽게 설명해 주세요.", context(topic_label="스레드"))
    assert [p.source_id for p in found] == ["3"]
    # 질문 낱말이 있으면 질문 낱말이 든 문단만 후보다. 문맥 낱말만 든 문단은 나오지 않는다.
    found = search_notes(NOTES, "멱등성", context(topic_label="스레드"))
    assert "3" not in [p.source_id for p in found]


def test_results_are_capped_and_fit_the_saved_shape():
    notes = [note(n, f"# 절 {n}\n멱등성 문단 {n}") for n in range(1, 10)]
    found = search_notes(notes, "멱등성", context())
    assert len(found) == MAX_RESULTS
    assert usable_paragraphs(found) == found


def test_notes_without_title_or_body_are_skipped():
    notes = [note(1, "멱등성", title=" "), {"id": 2, "revision": 1, "title": "t", "body_markdown": None}]
    assert search_notes(notes, "멱등성", context()) == []


@pytest.mark.parametrize("question", ["", "   ", "?!"])
def test_a_question_without_words_and_no_context_finds_nothing(question):
    assert search_notes(NOTES, question, context()) == []


def test_the_retriever_reads_only_published_note_bodies_and_reports_its_kind():
    class Store:
        calls = 0

        def list_published_note_bodies(self):
            self.calls += 1
            return NOTES

    store = Store()
    retriever = NoteRetriever(store)
    user = SessionUser(user_id="u", role="operator")
    assert [p.source_id for p in retriever.retrieve(user, "멱등성", context())] == ["1", "2"]
    assert store.calls == 1 and retriever.source_kind == "note" and retriever.version == "note-keyword-v1"


# --- 리뷰 지적 재현 (code-review high, 2026-11-18) ---


def test_latin_keywords_match_whole_words_only():
    notes = [note(1, "# a\nPUT 요청은 멱등하다."), note(2, "# b\noutput 과 input 을 본다.")]
    assert [p.source_id for p in search_notes(notes, "PUT", context())] == ["1"]


def test_image_syntax_with_a_title_or_escaped_bracket_becomes_alt_text():
    assert replace_images('앞 ![구조](note-image:k "그림 제목") 뒤') == "앞 [그림: 구조] 뒤"
    assert replace_images(r"![a\]b](note-image:k)") == r"[그림: a\]b]"
