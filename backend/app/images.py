"""사전 이미지 올리기(E22)의 파일 검사와 재인코딩 (API spec v0.2 2.4 E22, 1.4.4).

형식은 요청의 Content-Type이 아니라 파일 내용으로 판정한다. 메타데이터(EXIF·주석)를 지우려고 새 이미지에
픽셀만 옮겨 다시 저장한다. 크기·픽셀 상한은 가져오기 스크립트(backend/scripts/notion_images.py)와 같다.
가져오기는 모두 PNG로 바꾸지만 여기서는 원래 형식을 유지한다. 사진(JPEG)을 PNG로 바꾸면 몇 배로 커지기 때문이다(AI 제안).
- EXIF 회전 정보는 지우기 전에 픽셀에 적용한다. 그러지 않으면 휴대폰 사진이 옆으로 누워 저장된다.
- ICC 색 프로필은 남긴다. 개인 정보가 아니고, 지우면 넓은 색역 사진의 색이 달라진다.
"""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

# 요청 파일 상한 4MB(Vercel 본문 한도 4.5MB 아래, 기술 검토 구조 결정 9번)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
# 재인코딩 결과 상한. 버킷 file_size_limit(마이그레이션 20261102150000)과 같다.
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_SIDE = 8_000
MAX_PIXELS = 25_000_000

# Pillow 형식 -> (저장 형식, 확장자, Content-Type). 휴대폰 JPEG는 MPO(여러 장 JPEG)로 읽히므로 JPEG로 받는다.
_FORMATS = {
    "PNG": ("PNG", "png", "image/png"),
    "JPEG": ("JPEG", "jpg", "image/jpeg"),
    "MPO": ("JPEG", "jpg", "image/jpeg"),
    "WEBP": ("WEBP", "webp", "image/webp"),
}
# 믿을 수 없는 바이트에 이 밖의 Pillow 해석기를 쓰지 않는다. MPO는 별도 해석기가 아니라 JPEG 해석기가 판별한다.
_OPEN_FORMATS = ("PNG", "JPEG", "WEBP")


class ImageRejected(Exception):
    """kind: unsupported(415 형식), too_large(413 크기), invalid(422 invalid_format 재인코딩 실패)."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True)
class CleanImage:
    data: bytes
    extension: str
    content_type: str


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def reencode_upload(data: bytes) -> CleanImage:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected("too_large")
    try:
        with Image.open(BytesIO(data), formats=_OPEN_FORMATS) as source:
            image_format = source.format
            width, height = source.size
    except Image.DecompressionBombError:
        # 형식은 맞지만 픽셀이 너무 많다(머리말만 큰 파일 포함).
        raise ImageRejected("invalid") from None
    except (UnidentifiedImageError, OSError, ValueError):
        # 허용한 형식으로 읽히지 않는다(GIF·SVG·PDF·텍스트 등).
        raise ImageRejected("unsupported") from None
    if image_format not in _FORMATS:
        raise ImageRejected("unsupported")
    if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
        raise ImageRejected("invalid")
    save_format, extension, content_type = _FORMATS[image_format]
    try:
        with Image.open(BytesIO(data), formats=_OPEN_FORMATS) as source:
            source.verify()
        with Image.open(BytesIO(data), formats=_OPEN_FORMATS) as source:
            # 여러 장(움직이는 WebP, MPO)은 첫 장면만 남긴다.
            source.seek(0)
            source.load()
            icc_profile = source.info.get("icc_profile")
            upright = ImageOps.exif_transpose(source)
            mode = "RGBA" if save_format != "JPEG" and _has_alpha(upright) else "RGB"
            clean = Image.new(mode, upright.size)
            clean.paste(upright.convert(mode))
            options = {"icc_profile": icc_profile} if icc_profile else {}
            if save_format in ("JPEG", "WEBP"):
                options["quality"] = 85
            output = BytesIO()
            clean.save(output, format=save_format, **options)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        # 형식은 맞는데 내용이 깨졌다.
        raise ImageRejected("invalid") from None
    encoded = output.getvalue()
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ImageRejected("too_large")
    return CleanImage(encoded, extension, content_type)
