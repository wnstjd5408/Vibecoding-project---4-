"""사전 이미지 올리기(E22)의 파일 검사와 재인코딩 (API spec v0.2 2.4 E22, 1.4.4).

형식은 요청의 Content-Type이 아니라 파일 내용으로 판정한다. 메타데이터(EXIF·ICC·주석)를 지우려고 새 이미지에
픽셀만 옮겨 다시 저장한다. 크기·픽셀 상한은 가져오기 스크립트(backend/scripts/notion_images.py)와 같다.
가져오기는 모두 PNG로 바꾸지만 여기서는 원래 형식을 유지한다. 사진(JPEG)을 PNG로 바꾸면 몇 배로 커지기 때문이다(AI 제안).
"""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

# 요청 파일 상한 4MB(Vercel 본문 한도 4.5MB 아래, 기술 검토 구조 결정 9번)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
# 재인코딩 결과 상한. 버킷 file_size_limit(마이그레이션 20261102150000)과 같다.
MAX_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_SIDE = 8_000
MAX_PIXELS = 25_000_000

# Pillow 형식 -> (확장자, Content-Type)
_FORMATS = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}


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


def reencode_upload(data: bytes) -> CleanImage:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected("too_large")
    try:
        with Image.open(BytesIO(data)) as source:
            image_format = source.format
            width, height = source.size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        # 이미지로 읽히지 않는다(PDF·SVG·텍스트 등). 허용 형식이 아니다.
        raise ImageRejected("unsupported") from None
    if image_format not in _FORMATS:
        raise ImageRejected("unsupported")
    if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
        raise ImageRejected("invalid")
    extension, content_type = _FORMATS[image_format]
    try:
        with Image.open(BytesIO(data)) as source:
            source.verify()
        with Image.open(BytesIO(data)) as source:
            # 움직이는 WebP는 첫 장면만 남긴다.
            source.seek(0)
            source.load()
            output = BytesIO()
            if image_format == "JPEG":
                clean = Image.new("RGB", source.size)
                clean.paste(source.convert("RGB"))
                clean.save(output, format="JPEG", quality=90)
            else:
                clean = Image.new("RGBA", source.size)
                clean.paste(source.convert("RGBA"))
                clean.save(output, format=image_format, **({"quality": 90} if image_format == "WEBP" else {}))
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        # 형식은 맞는데 내용이 깨졌다.
        raise ImageRejected("invalid") from None
    encoded = output.getvalue()
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ImageRejected("too_large")
    return CleanImage(encoded, extension, content_type)
