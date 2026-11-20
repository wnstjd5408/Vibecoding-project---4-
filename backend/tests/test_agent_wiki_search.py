"""CS Agent 위키 검색(MEG-251 T4b)의 읽는 범위·식별자·가산점·중복 제거·상한·로그 (설계 v0.3 3.2·3.5절, S1·S2·S10).

DB와 모델 없이 도는 단위 시험이다. 데이터는 모두 합성이다. 실제 래퍼의 DB 필터는 test_supabase_agent_client.py가 본다.
"""

import logging

import pytest

from app.agent_note_search import note_chunks
from app.agent_retrieval import RetrievalContext
from app.agent_wiki_search import (
    MAX_PER_ENTRY,
    MAX_RESULTS,
    RETRIEVAL_VERSION,
    SOURCE_KIND,
    WikiRetriever,
    parse_wiki_ref,
    resolve_term,
    search_wiki,
    wiki_entries,
    wiki_source_id,
)
from app.auth import SessionUser

USER = SessionUser("00000000-0000-4000-8000-00000000000a", "member")
# T4a(MEG-249, PR #187) 병합 전이므로 glossary_revision은 시험용 값이다.
TEST_REVISION = 7


def context(**overrides) -> RetrievalContext:
    values = {"conversation_id": "c", "origin": "none", "note_id": None, "topic_label": "", **overrides}
    return RetrievalContext(**values)


def entry(term_id: int, label: str, body: str, *, key: str | None = None, source: str = "glossary",
          revision=TEST_REVISION, has_entry: bool = True) -> dict:
    return {
        "id": term_id,
        "key": key if key is not None else label.lower(),
        "label": label,
        "source": source,
        "glossary_revision": revision,
        "glossary_entries": {"body_markdown": body} if has_entry else None,
    }


class FakeWiki:
    """list_wiki_entries만 있는 가짜 DB. 노트를 읽는 메서드가 없으므로 노트를 읽으려 하면 AttributeError다."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def list_wiki_entries(self):
        self.calls += 1
        return self.rows


DNS = entry(2, "DNS", "# 정의\nDNS는 도메인 이름을 IP 주소로 바꾼다.\n\n# 캐시\n리졸버는 응답을 TTL 동안 캐시한다.")
TCP = entry(3, "TCP", "# 정의\nTCP는 연결형 전송 계층 프로토콜이다.\n\n# 연결 수립\n3-way handshake로 연결을 맺는다.")


# --- AC-1: 읽는 범위(S1·S2) ---


def test_only_current_dictionary_entries_are_searched():
    rows = [
        DNS,
        # 사전 삭제(E21) 뒤 terms 행만 남은 용어: source가 ai이고 본문이 없다.
        entry(4, "캐시", "", source="ai", has_entry=False),
        # source가 ai인데 본문이 남은(어긋난) 행도 위키가 아니다. AI 설명으로 AI 답을 뒷받침하지 않는다.
        entry(5, "라우팅", "# 정의\n라우팅 캐시 DNS 삭제된 본문", source="ai"),
        # source는 glossary인데 glossary_entries 행이 없는 것도 없는 항목이다.
        entry(6, "포트", "", has_entry=False),
    ]
    found = search_wiki(rows, "DNS 캐시", context())
    assert found and {p.source_id for p in found} == {"glossary:2"}
    assert all(p.source_kind == SOURCE_KIND == "wiki" for p in found)


def test_rows_with_a_bad_revision_or_shape_are_skipped_and_counted():
    rows = [
        DNS,
        entry(7, "A", "# 정의\nDNS 문단", revision=None),
        entry(8, "B", "# 정의\nDNS 문단", revision=-1),
        entry(9, "C", "# 정의\nDNS 문단", revision=True),
        entry(10, "D", "# 정의\nDNS 문단", revision="3"),
        {**DNS},  # 같은 term_id가 두 번 오면 처음 것만 쓴다.
        {**entry(11, "E", "# 정의\nDNS 문단"), "id": "11"},
        entry(12, " ", "# 정의\nDNS 문단"),
    ]
    entries, skipped = wiki_entries(rows)
    assert [e.term_id for e in entries] == [2] and skipped == 7


def test_the_retriever_reads_only_the_wiki_source_and_never_notes():
    source = FakeWiki([DNS, TCP])
    retriever = WikiRetriever(source)
    assert (retriever.version, retriever.source_kind) == (RETRIEVAL_VERSION, "wiki") == ("wiki-keyword-v1", "wiki")
    found = retriever.retrieve(USER, "TCP 연결", context(origin="note", note_id=1, selection_note_ids=(1,),
                                                         selection_texts=("노트 문장",)))
    assert source.calls == 1 and found and all(p.source_kind == "wiki" for p in found)


def test_a_paragraph_carries_the_glossary_id_revision_label_and_section():
    [paragraph] = search_wiki([DNS], "리졸버 TTL", context())
    assert paragraph.source_id == "glossary:2" and paragraph.revision == str(TEST_REVISION)
    assert (paragraph.title, paragraph.section, paragraph.text) == ("DNS", "캐시", "리졸버는 응답을 TTL 동안 캐시한다.")


def test_entries_are_split_with_the_note_chunk_rule():
    body = "머리말.\n\n# 긴 절\n" + "\n\n".join(f"{n}번 단락 " + "가" * 590 for n in range(4))
    rows = [entry(20, "긴항목", body)]
    found = search_wiki(rows, "긴항목", context())
    chunks = note_chunks(body)
    assert len(chunks) > 1
    assert {(p.section, p.text) for p in found} <= {(c.section, c.text) for c in chunks}


# --- 가산점 ---


def test_the_wiki_ref_entry_is_a_candidate_even_without_question_words():
    # "더 쉽게 설명해 주세요"는 흔한 말뿐이라 질문 낱말이 없다.
    assert search_wiki([DNS, TCP], "더 쉽게 설명해 주세요", context()) == []
    found = search_wiki([DNS, TCP], "더 쉽게 설명해 주세요", context(origin="wiki", wiki_ref="glossary:3"))
    assert [p.section for p in found] == ["정의", "연결 수립"] and {p.source_id for p in found} == {"glossary:3"}


def test_the_wiki_ref_entry_ranks_first_when_scores_would_tie():
    question = "전송 계층 프로토콜"
    udp = entry(4, "UDP", "# 정의\nUDP는 비연결형 전송 계층 프로토콜이다.")
    plain = search_wiki([TCP, udp], question, context())
    assert plain[0].source_id == "glossary:3"
    referred = search_wiki([TCP, udp], question, context(origin="wiki", wiki_ref="glossary:4"))
    assert referred[0].source_id == "glossary:4"


def test_a_term_named_in_the_question_or_selection_gets_a_bonus():
    # 질문 낱말("과정")은 어느 항목에도 없지만 선택 문맥에 TCP가 있다.
    found = search_wiki([DNS, TCP], "이 과정", context(selection_note_ids=(1,), selection_texts=("TCP 연결 과정",)))
    assert found and {p.source_id for p in found} == {"glossary:3"}
    assert search_wiki([DNS, TCP], "이 과정", context()) == []


def test_an_invalid_wiki_ref_gives_no_bonus():
    for ref in ("glossary:03", "glossary:-3", "glossary: 3", "3", "note:3", "glossary:3#정의"):
        assert search_wiki([DNS, TCP], "더 쉽게 설명해 주세요", context(wiki_ref=ref)) == []


# --- 중복 제거와 상한 ---


def test_identical_paragraphs_are_returned_once():
    shared = "# 참고\n전송 계층 비교표는 네트워크 노트에서 본다."
    rows = [entry(3, "TCP", shared), entry(4, "UDP", shared)]
    found = search_wiki(rows, "전송 계층 비교표", context())
    assert [p.source_id for p in found] == ["glossary:3"]


def test_one_entry_gives_at_most_three_paragraphs_and_the_total_is_capped():
    body = "\n\n".join(f"# 절{n}\n공통 낱말 문단 {n}" for n in range(6))
    rows = [entry(30 + n, f"항목{n}", body.replace("문단", f"문단{n}")) for n in range(3)]
    found = search_wiki(rows, "공통 낱말", context())
    assert MAX_PER_ENTRY == 3 and MAX_RESULTS == 5
    assert len(found) == MAX_RESULTS
    counts = {}
    for paragraph in found:
        counts[paragraph.source_id] = counts.get(paragraph.source_id, 0) + 1
    assert max(counts.values()) <= MAX_PER_ENTRY


def test_search_is_deterministic():
    rows = [DNS, TCP, entry(4, "UDP", "# 정의\nUDP도 전송 계층 프로토콜이다.")]
    first = search_wiki(rows, "전송 계층 프로토콜 DNS", context())
    assert first == search_wiki(list(reversed(rows)), "전송 계층 프로토콜 DNS", context())


# --- 식별자와 표기 연결 ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [("glossary:17", 17), ("glossary:9223372036854775807", 2**63 - 1), ("glossary:9223372036854775808", None),
     ("glossary:0", None), ("glossary:017", None), ("Glossary:17", None), ("glossary:17 ", None),
     ("glossary:１７", None), ("", None), (None, None), (17, None)],
)
def test_wiki_ref_parsing(value, expected):
    assert parse_wiki_ref(value) == expected


def test_source_id_format():
    assert wiki_source_id(17) == "glossary:17" and parse_wiki_ref(wiki_source_id(17)) == 17


def test_a_label_resolves_to_its_entry_only_when_the_whole_text_matches():
    entries, _ = wiki_entries([DNS, TCP, entry(4, "캐시", "", source="ai", has_entry=False)])
    assert resolve_term("DNS", entries) == 2
    assert resolve_term(" dns ", entries) == 2
    assert resolve_term("DNS 캐시", entries) is None
    assert resolve_term("캐시", entries) is None  # 지운 항목은 대표 페이지가 없다.
    assert resolve_term("라우터", entries) is None


# --- AC-2: 기존 문맥과의 호환 ---


def test_the_context_field_defaults_to_none():
    assert context().wiki_ref is None


# --- AC-4: 로그(S10) ---


def test_the_retrieve_log_has_stage_and_counts_but_no_question_or_dictionary_text(caplog):
    question = "리졸버 TTL 비밀질문문장"
    rows = [DNS, entry(4, "캐시", "", source="ai", has_entry=False)]
    with caplog.at_level(logging.INFO, logger="app.agent"):
        found = WikiRetriever(FakeWiki(rows)).retrieve(USER, question, context(selection_texts=("선택비밀문장",)))
    messages = [record.getMessage() for record in caplog.records if record.name == "app.agent"]
    assert messages == ["stage=retrieve source_kind=wiki entries=1 skipped=1 paragraphs=1"]
    text = "\n".join(messages)
    for secret in (question, "비밀질문문장", "선택비밀문장", found[0].text, "리졸버", "DNS"):
        assert secret not in text
