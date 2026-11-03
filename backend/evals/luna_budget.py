"""Service-envelope reservation; deliberately not an input-token estimate.

Source: AWS Luna model card, checked 2026-11-02. Global Standard only.
Context 1,050,000; long-context input/cache-write/output per MTok: .20/.25/.75.
"""
from decimal import Decimal
import json

from .schema import DatasetError

POLICY = "luna-service-envelope-2026-11-02"
CONTEXT_LIMIT = 1050000
MAX_REQUEST_BYTES = 16000


def reservation(config, requests):
    if (config.model_id != "global.openai.gpt-6-luna"
            or config.max_input != CONTEXT_LIMIT or config.max_output > 8192
            or Decimal(config.input_price) != Decimal("0.20")
            or Decimal(config.output_price) != Decimal("0.75")
            or config.price_version != POLICY):
        raise DatasetError("live: envelope_policy_mismatch")
    for request in requests.values():
        # A product payload-size guard, NOT a claim about tokenizer behavior.
        if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
            raise DatasetError("live: request_byte_limit")
    # Assume every input token is billed at the highest cache-write rate.
    # Output is reserved separately even though context is a combined limit.
    return (Decimal("0.25") * CONTEXT_LIMIT + Decimal("0.75") * config.max_output) / 1000000


def usage_estimate(inp, out, read, write):
    """Conservative estimate. Keep raw usage for AWS invoice reconciliation."""
    total_input = inp + read + write
    long = total_input > 272000
    base, cached, creation, output = (map(Decimal, (".20", ".02", ".25", ".75")) if long
                                    else map(Decimal, (".10", ".01", ".125", ".50")))
    return (inp * base + read * cached + write * creation + out * output) / 1000000
