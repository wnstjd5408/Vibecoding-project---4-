import pytest


@pytest.mark.skip(reason="MEG-175 intentional required-test skip; do not merge")
def test_required_ci_probe():
    assert True
