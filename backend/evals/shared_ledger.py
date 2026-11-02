"""Server-only Supabase RPC ledger; SQL must be applied and approval provisioned first."""
import json
import os
from urllib.parse import urlparse

import httpx

from .schema import DatasetError


class SharedLedger:
    def __init__(self, url, secret, approval_id, *, client=None):
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or not secret or not approval_id):
            raise DatasetError("live: ledger_config")
        self.url = url.rstrip("/")
        self.approval_id = approval_id
        self.headers = {"apikey": secret, "Content-Type": "application/json"}
        # Legacy service_role JWT needs Authorization; modern secret key uses apikey.
        if secret.startswith("eyJ"):
            self.headers["Authorization"] = "Bearer " + secret
        self.client = client or httpx.Client(timeout=20, follow_redirects=False,
                                             transport=httpx.HTTPTransport(retries=0))

    @classmethod
    def from_env(cls):
        values = [os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "EVAL_APPROVAL_ID")]
        if not all(values):
            raise DatasetError("live: ledger_config_missing")
        return cls(*values)

    def _rpc(self, name, body):
        try:
            result = self.client.post(self.url + "/rest/v1/rpc/" + name,
                                      headers=self.headers, content=json.dumps(body))
            if result.status_code != 200 or result.json() is not True:
                raise DatasetError("live: ledger_rejected")
        except DatasetError:
            raise
        except (httpx.HTTPError, ValueError):
            raise DatasetError("live: ledger_unavailable") from None

    def reserve(self, run_id, slot, identity, amount):
        self._rpc("eval_reserve", {"p_approval": self.approval_id, "p_run": run_id,
                  "p_slot": slot, "p_identity": identity, "p_amount": amount})

    def finish(self, run_id, slot, row):
        self._rpc("eval_finish", {"p_approval": self.approval_id, "p_run": run_id,
                  "p_slot": slot, "p_result": row})
