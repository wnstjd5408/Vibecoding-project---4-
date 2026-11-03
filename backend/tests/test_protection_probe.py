import pytest


@pytest.mark.skip(reason="MEG-180 required-test protection probe; never merge")
def test_required_suite_must_reject_skip():
    assert True
