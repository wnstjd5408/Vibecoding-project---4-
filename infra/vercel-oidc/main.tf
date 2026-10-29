# Vercel 배포의 FastAPI가 Bedrock을 부를 때 맡는 역할(MEG-119, MEG-118).
# 이 폴더는 사람이 로컬에서만 apply한다. Infra CD의 apply 역할에는 IAM 쓰기 권한이 없다.
#
# Vercel 프로젝트는 team issuer 모드다. 토큰 형식(https://vercel.com/docs/oidc/reference):
# - iss: https://oidc.vercel.com/<team>
# - aud: https://vercel.com/<team> (백엔드가 요청 헤더의 토큰을 그대로 STS에 넘기므로 기본값을 쓴다.
#   이 토큰을 STS 말고 다른 서비스에 넘기면 그 서비스도 이 역할을 맡을 수 있으니 넘기지 않는다)
# - sub: owner:<team>:project:<project>:environment:<env>
#
# sub에 브랜치가 없어서 Preview 역할은 staging뿐 아니라 모든 Preview 배포(PR 포함)가 맡을 수 있다.
# 빌드 단계에도 토큰이 나오므로 PR이 바꾼 빌드 스크립트도 포함된다. 이 신뢰 정책만으로는 막지 못한다.
# staging 밖의 Preview는 백엔드가 STS 호출 전에 막을 예정이다(MEG-120). 그 전까지는 AWS_ROLE_ARN을
# Preview의 staging 브랜치 범위에만 넣는 것이 유일한 장치다.

locals {
  account_id = data.aws_caller_identity.current.account_id
  oidc_host  = "oidc.vercel.com/${var.vercel_team_slug}"
  oidc_aud   = "https://vercel.com/${var.vercel_team_slug}"

  # 역할 이름 접미사 → 토큰의 environment 값. 역할을 환경별로 나눠 Preview 토큰이 운영 역할을 맡지 못하게 한다.
  environments = {
    prd     = "production"
    preview = "preview"
  }

  profile_arn     = "arn:aws:bedrock:${var.bedrock_region}:${local.account_id}:inference-profile/global.${var.bedrock_model_id}"
  regional_fm_arn = "arn:aws:bedrock:${var.bedrock_region}::foundation-model/${var.bedrock_model_id}"
  global_fm_arn   = "arn:aws:bedrock:::foundation-model/${var.bedrock_model_id}"
}

resource "aws_iam_openid_connect_provider" "vercel" {
  url            = "https://${local.oidc_host}"
  client_id_list = [local.oidc_aud]
}

data "aws_iam_policy_document" "trust" {
  for_each = local.environments

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.vercel.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = [local.oidc_aud]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = ["owner:${var.vercel_team_slug}:project:${var.vercel_project_name}:environment:${each.value}"]
    }
  }
}

resource "aws_iam_role" "bedrock" {
  for_each = local.environments

  name = "${var.owner}-vercel-bedrock-${each.key}"
  # IAM 설명에는 한글을 쓸 수 없다(MEG-100).
  description          = "Vercel ${each.value} deployments call Bedrock through OIDC (MEG-118)"
  assume_role_policy   = data.aws_iam_policy_document.trust[each.key].json
  max_session_duration = 3600
}

# 글로벌 추론 프로필 호출에 필요한 3문장(AWS 문서 "Global cross-Region inference"의 IAM 예시).
# 추론 프로필 → 호출 리전의 기반 모델 → 글로벌 기반 모델. 모델 문장은 이 추론 프로필을 거칠 때만 허용한다.
# Converse API도 bedrock:InvokeModel 권한으로 검사한다. 스트리밍(ConverseStream)은
# bedrock:InvokeModelWithResponseStream이 따로 필요하며, 지금 백엔드는 쓰지 않아 주지 않았다.
data "aws_iam_policy_document" "bedrock" {
  statement {
    sid       = "InferenceProfile"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.profile_arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.bedrock_region]
    }
  }

  statement {
    sid       = "RegionalModel"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.regional_fm_arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.bedrock_region]
    }

    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.profile_arn]
    }
  }

  statement {
    sid       = "GlobalModel"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.global_fm_arn]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = ["unspecified"]
    }

    condition {
      test     = "StringEquals"
      variable = "bedrock:InferenceProfileArn"
      values   = [local.profile_arn]
    }
  }
}

resource "aws_iam_role_policy" "bedrock" {
  for_each = local.environments

  name   = "bedrock-invoke"
  role   = aws_iam_role.bedrock[each.key].id
  policy = data.aws_iam_policy_document.bedrock.json
}
