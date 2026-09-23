"""Build image-bearing request payloads for Converse and the Responses API.

Two mistakes are easy to make by hand and both produce a confusing failure mode
where the vision smoke test passes (it hardcodes a known-good jpeg) while every
golden case fails:

1. **Extension is not the wire format.** A `.jpg` file is `jpeg` for Converse and
   `image/jpeg` for Responses. Passing `jpg` / `image/jpg` is rejected.
2. **Responses content must be wrapped in a message item.** A bare
   `[{"type": "input_text", ...}]` list is not a valid `input`; it has to be
   `[{"role": "user", "content": [...]}]`.
3. **`detail` is required on a Responses image block.** The pinned OpenAI SDK
   declares `ResponseInputImageParam.detail` as `Required`, so omitting it is a
   contract violation even though a TypedDict will not catch it at runtime.

Callers should use `converse_message` / `responses_message` rather than assembling
these dicts inline, so the shape is decided in one tested place.
"""
from pathlib import Path

# Accepted by ResponseInputImageParam.detail; "auto" is the SDK's documented default.
DETAIL_LEVELS = ("low", "high", "auto", "original")
DEFAULT_DETAIL = "auto"

# Formats Bedrock Converse accepts, keyed by the extensions that map onto them.
_CONVERSE_FORMATS = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
}


def converse_format(image_path: str) -> str:
    """Converse `image.format` value for a file path. Raises on unsupported types.

    Note `.jpg` -> `jpeg`: the extension and the wire format differ, and Converse
    rejects `jpg`.
    """
    ext = Path(image_path).suffix.lstrip(".").lower()
    if ext not in _CONVERSE_FORMATS:
        raise ValueError(
            f"unsupported image type {ext!r} for {image_path}: "
            f"Bedrock accepts {sorted(set(_CONVERSE_FORMATS.values()))}")
    return _CONVERSE_FORMATS[ext]


def mime_type(image_path: str) -> str:
    """MIME type for a data URL, e.g. `.jpg` -> `image/jpeg` (never `image/jpg`)."""
    return f"image/{converse_format(image_path)}"


def data_url(image_path: str, raw: bytes) -> str:
    """base64 data URL for the Responses API `input_image.image_url` field."""
    import base64
    return f"data:{mime_type(image_path)};base64,{base64.b64encode(raw).decode()}"


def converse_message(prompt: str, image_path: str | None = None,
                     raw: bytes | None = None) -> dict:
    """One Converse `messages[]` item. Image block precedes the text block."""
    content: list[dict] = []
    if image_path is not None:
        if raw is None:
            raise ValueError("raw image bytes are required when image_path is given")
        content.append({"image": {"format": converse_format(image_path),
                                  "source": {"bytes": raw}}})
    content.append({"text": prompt})
    return {"role": "user", "content": content}


def responses_message(prompt: str, image_path: str | None = None,
                      raw: bytes | None = None, detail: str = DEFAULT_DETAIL) -> dict:
    """One Responses API `input[]` item, wrapped as a user message.

    Returning the wrapper (rather than a bare content list) is the point: an
    unwrapped list is invalid input, and that is the easiest thing to get wrong.
    `detail` is always emitted because the SDK declares it Required.
    """
    if detail not in DETAIL_LEVELS:
        raise ValueError(f"invalid image detail {detail!r}: expected one of {list(DETAIL_LEVELS)}")
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    if image_path is not None:
        if raw is None:
            raise ValueError("raw image bytes are required when image_path is given")
        content.append({"type": "input_image",
                        "image_url": data_url(image_path, raw),
                        "detail": detail})
    return {"role": "user", "content": content}
