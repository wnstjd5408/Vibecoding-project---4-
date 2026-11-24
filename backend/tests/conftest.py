"""모든 시험에 공통인 준비.

위키 플래그(CS_AGENT_WIKI_ENABLED, MEG-252)는 기본 꺼짐이다. 개발자 셸에 켜 둔 값이 있어도 시험은 꺼진 상태에서 시작한다.
켠 상태를 보는 시험은 monkeypatch.setenv로 직접 켠다.
"""

import pytest

from app.agent_retrieval import WIKI_ENV


@pytest.fixture(autouse=True)
def _wiki_flag_off(monkeypatch):
    monkeypatch.delenv(WIKI_ENV, raising=False)
