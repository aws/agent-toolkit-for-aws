# test_image_input.py
"""Regression coverage for the two vision payload mistakes that let a smoke test
pass while every golden case fails."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import image_input as ii

RAW = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_jpg_extension_normalizes_to_jpeg():
    # Regression: `.jpg` passed through verbatim produced Converse `format: 'jpg'`
    # and MIME `image/jpg`, both rejected. The smoke test hardcodes 'jpeg' and so
    # never surfaced it.
    assert ii.converse_format("cat.jpg") == "jpeg"
    assert ii.converse_format("cat.jpeg") == "jpeg"
    assert ii.mime_type("cat.jpg") == "image/jpeg"
    assert "image/jpg" not in ii.data_url("cat.jpg", RAW)


def test_extension_case_is_ignored():
    assert ii.converse_format("CAT.JPG") == "jpeg"
    assert ii.mime_type("shot.PNG") == "image/png"


@pytest.mark.parametrize("name,fmt", [
    ("a.png", "png"), ("a.gif", "gif"), ("a.webp", "webp"),
])
def test_other_supported_formats(name, fmt):
    assert ii.converse_format(name) == fmt
    assert ii.mime_type(name) == f"image/{fmt}"


@pytest.mark.parametrize("name", ["a.bmp", "a.tiff", "a.svg", "a.heic", "noext"])
def test_unsupported_types_raise_rather_than_guess(name):
    # Silently passing an unsupported extension through would produce an opaque
    # API rejection at eval time instead of a clear failure here.
    with pytest.raises(ValueError, match="unsupported image type"):
        ii.converse_format(name)


def test_responses_message_is_wrapped_as_a_user_message():
    # Regression: the per-case loop passed a bare [{'type': 'input_text', ...}]
    # list as `input`, which is not a valid Responses request.
    msg = ii.responses_message("describe", "cat.jpg", RAW)
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    kinds = [b["type"] for b in msg["content"]]
    assert kinds == ["input_text", "input_image"]
    assert msg["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert base64.b64encode(RAW).decode() in msg["content"][1]["image_url"]


def test_responses_message_text_only_omits_the_image_block():
    msg = ii.responses_message("describe")
    assert msg["role"] == "user"
    assert [b["type"] for b in msg["content"]] == ["input_text"]


def test_converse_message_puts_image_before_text():
    msg = ii.converse_message("describe", "cat.jpg", RAW)
    assert msg["role"] == "user"
    assert list(msg["content"][0]) == ["image"]
    assert msg["content"][0]["image"]["format"] == "jpeg"
    assert msg["content"][0]["image"]["source"]["bytes"] is RAW
    assert msg["content"][1] == {"text": "describe"}


def test_converse_message_text_only():
    assert ii.converse_message("describe") == {
        "role": "user", "content": [{"text": "describe"}]}


@pytest.mark.parametrize("fn", [ii.converse_message, ii.responses_message])
def test_image_path_without_bytes_is_an_error(fn):
    with pytest.raises(ValueError, match="raw image bytes"):
        fn("describe", "cat.jpg", None)


def test_responses_image_block_sets_detail():
    # Regression: `detail` is Required on ResponseInputImageParam in the pinned SDK,
    # and omitting it is a contract violation a TypedDict will not catch at runtime.
    block = ii.responses_message("describe", "cat.jpg", RAW)["content"][1]
    assert block["detail"] == "auto"


def _sdk_image_param_keys() -> tuple[set[str], set[str]]:
    """(required, all) keys of ResponseInputImageParam, read from the pinned SDK.

    `__required_keys__` is unusable here: the class is declared `total=False` with
    per-field `Required[...]` markers, which CPython 3.11 does not fold into
    `__required_keys__` — it reports every key as optional. The annotation origin
    does carry the marker, so read requiredness from there.
    """
    import typing_extensions as te
    from openai.types.responses import ResponseInputImageParam

    hints = te.get_type_hints(ResponseInputImageParam, include_extras=True)
    required = {k for k, v in hints.items() if te.get_origin(v) is te.Required}
    return required, set(hints)


def test_responses_image_block_satisfies_the_pinned_sdk_required_fields():
    # Derive the requirement from the installed SDK rather than restating it, so a
    # future SDK bump that adds a required field fails here instead of at runtime.
    required, known = _sdk_image_param_keys()
    assert "detail" in required, "SDK no longer marks detail required — revisit this test"
    block = ii.responses_message("describe", "cat.jpg", RAW)["content"][1]
    missing = required - set(block)
    assert not missing, f"image block missing SDK-required field(s): {sorted(missing)}"
    unknown = set(block) - known
    assert not unknown, f"image block has field(s) the SDK does not define: {sorted(unknown)}"


@pytest.mark.parametrize("detail", ["low", "high", "auto", "original"])
def test_all_sdk_detail_levels_accepted(detail):
    block = ii.responses_message("d", "cat.png", RAW, detail=detail)["content"][1]
    assert block["detail"] == detail


def test_invalid_detail_rejected():
    with pytest.raises(ValueError, match="invalid image detail"):
        ii.responses_message("d", "cat.png", RAW, detail="ultra")


def test_detail_levels_match_the_pinned_sdk_literal():
    import typing_extensions as te
    from openai.types.responses import ResponseInputImageParam
    hints = te.get_type_hints(ResponseInputImageParam, include_extras=True)
    literal = te.get_args(te.get_args(hints["detail"])[0])   # unwrap Required[Literal[...]]
    assert set(literal) == set(ii.DETAIL_LEVELS)


def test_text_only_message_has_no_detail_key():
    # detail belongs to the image block only; a stray key on the text block would
    # be an unknown field.
    msg = ii.responses_message("describe")
    assert "detail" not in msg["content"][0]
