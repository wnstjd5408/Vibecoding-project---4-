from dataclasses import replace
from decimal import Decimal

import httpx
import pytest

from evals import luna_budget, live
from evals.shared_ledger import SharedLedger
from evals.schema import DatasetError
from test_eval_live import setup, response, no_network


def envelope(monkeypatch):
    cases, manifest, config = setup(monkeypatch, False)
    return cases, manifest, replace(config, max_input=1050000, max_output=8192,
        tokenizer_version=luna_budget.POLICY, price_version=luna_budget.POLICY,
        input_price=".20", output_price=".75")


def test_service_reservation_no_tokenizer(monkeypatch, tmp_path):
    args = envelope(monkeypatch)
    def forbidden(_):
        pytest.fail("tokenizer called")
    monkeypatch.setattr(live, "input_bound", forbidden)
    state = live.calibration(*args, tmp_path, ["C0","C1","C2"], lambda _: response())
    assert state["provider_calls"] == 3
    assert sum(Decimal(r["reserved_cost"]) for r in state["slots"].values()) == Decimal(".805932")
    assert state["slots"]["C0"]["cost_upper_estimate"] == "0.00002"


@pytest.mark.parametrize("change", [{"budget":".80"}, {"max_output":8193},
    {"input_price":".10"}, {"max_input":4000}, {"price_version":"old"}])
def test_bad_policy_no_call(monkeypatch,tmp_path,change):
    cases, manifest, config = envelope(monkeypatch)
    with pytest.raises(DatasetError):
        live.calibration(cases,manifest,replace(config,**change),tmp_path,["C0","C1","C2"],
                         lambda _: pytest.fail("called"))


def test_byte_guard_not_token_claim(monkeypatch):
    config = envelope(monkeypatch)[2]
    with pytest.raises(DatasetError,match="byte_limit"):
        luna_budget.reservation(config,{"x":{"text":"가"*16000}})


def test_shared_failure_prevents_provider(monkeypatch,tmp_path):
    class Ledger:
        def reserve(self,*a):
            raise DatasetError("ledger down")
    with pytest.raises(DatasetError,match="ledger down"):
        live.calibration(*envelope(monkeypatch),tmp_path,["C0"],lambda _:pytest.fail("called"),ledger=Ledger())
    with pytest.raises(DatasetError,match="manual_recovery"):
        live.calibration(*envelope(monkeypatch),tmp_path,["C0"],lambda _:pytest.fail("called"),ledger=Ledger())


def test_shared_rpc_no_retry():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(503,text="private error")
    client=httpx.Client(transport=httpx.MockTransport(handler))
    ledger=SharedLedger("https://fixture.supabase.co","fixture-secret","approval",client=client)
    with pytest.raises(DatasetError,match="ledger_rejected") as error:
        ledger.reserve("run","C0","hash","0.1")
    assert len(calls)==1 and "private error" not in str(error.value)


def test_usage_long_context():
    assert luna_budget.usage_estimate(300000,100,0,0)==Decimal(".060075")
