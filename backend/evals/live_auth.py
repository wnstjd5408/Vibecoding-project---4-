"""Explicit OIDC authentication for an approved evaluation environment."""
import os

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .live import BedrockTransport, SDK_CONFIG
from .schema import DatasetError


def oidc_transport():
    role = os.environ.get("AWS_ROLE_ARN")
    token = os.environ.get("VERCEL_OIDC_TOKEN")
    if not role or not token:
        raise DatasetError("live: oidc_credentials_missing")
    try:
        sts = boto3.client("sts", region_name="ap-northeast-1",
                           config=SDK_CONFIG.merge(Config(signature_version=UNSIGNED)))
        credentials = sts.assume_role_with_web_identity(
            RoleArn=role, RoleSessionName="cs-eval-calibration",
            WebIdentityToken=token, DurationSeconds=900)["Credentials"]
        client = boto3.client("bedrock-runtime", region_name="ap-northeast-1",
                              aws_access_key_id=credentials["AccessKeyId"],
                              aws_secret_access_key=credentials["SecretAccessKey"],
                              aws_session_token=credentials["SessionToken"],
                              config=SDK_CONFIG.merge(Config(signature_version="v4")))
        return BedrockTransport(client)
    except (ClientError, BotoCoreError):
        raise DatasetError("live: authentication_failed") from None
