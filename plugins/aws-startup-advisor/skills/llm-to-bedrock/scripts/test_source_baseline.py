"""Locks for the baseline runner's request shapes and key hygiene.

The request builders are pure (no network), so the provider API shapes and the
never-key-in-URL rule are pinned here without mocking urllib.
"""
import os
import pathlib

import source_baseline as sb


def _with_keys(**keys):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        os.environ.pop(k, None)
    os.environ.update(keys)


def test_openai_shape_uses_max_completion_tokens():
    _with_keys(OPENAI_API_KEY="sk-test")
    url, headers, body = sb.build_openai_request("gpt-4o", "sys", "hi")
    assert url == "https://api.openai.com/v1/chat/completions"
    assert body["max_completion_tokens"] == sb.MAX_TOKENS
    assert "max_tokens" not in body, "gpt-5.x rejects max_tokens (HTTP 400)"
    assert body["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_no_system_message_when_empty():
    _with_keys(OPENAI_API_KEY="sk-test")
    _, _, body = sb.build_openai_request("gpt-4o", "", "hi")
    assert [m["role"] for m in body["messages"]] == ["user"]


def test_anthropic_shape_uses_top_level_system():
    _with_keys(ANTHROPIC_API_KEY="sk-ant")
    url, headers, body = sb.build_anthropic_request("claude-3-5-sonnet", "sys", "hi")
    assert url == "https://api.anthropic.com/v1/messages"
    assert body["system"] == "sys"
    assert headers["anthropic-version"] == "2023-06-01"
    assert body["max_tokens"] == sb.MAX_TOKENS


def test_gemini_key_in_header_never_in_url():
    _with_keys(GEMINI_API_KEY="AIza-test")
    url, headers, body = sb.build_gemini_request("gemini-1.5-pro", "sys", "hi")
    assert "AIza-test" not in url, "key must never be a URL query parameter"
    assert "key=" not in url
    assert headers["x-goog-api-key"] == "AIza-test"
    assert body["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert body["generationConfig"]["maxOutputTokens"] == sb.MAX_TOKENS


def test_all_provider_urls_are_official_hosts():
    # Security note in the skill: the key only ever travels to its own
    # provider's official endpoint.
    _with_keys(OPENAI_API_KEY="a", ANTHROPIC_API_KEY="b", GEMINI_API_KEY="c")
    urls = [
        sb.build_openai_request("m", "", "x")[0],
        sb.build_anthropic_request("m", "", "x")[0],
        sb.build_gemini_request("m", "", "x")[0],
    ]
    allowed = ("https://api.openai.com/", "https://api.anthropic.com/",
               "https://generativelanguage.googleapis.com/")
    for u in urls:
        assert u.startswith(allowed), u


def test_env_file_loader_ignores_blank_and_malformed_lines(tmp_path: pathlib.Path):
    p = tmp_path / ".source-provider-env"
    p.write_text("\n# comment-ish\nOPENAI_API_KEY=sk-live\n", encoding="utf-8")
    os.environ.pop("OPENAI_API_KEY", None)
    sb.load_env_file(str(p))
    assert os.environ["OPENAI_API_KEY"] == "sk-live"


def test_provider_selected_from_file_not_ambient_env(tmp_path):
    # Review finding: file is authoritative; ambient keys must not win.
    _with_keys(OPENAI_API_KEY="sk-ambient")
    p = tmp_path / ".source-provider-env"
    p.write_text("GEMINI_API_KEY=AIza-file\n", encoding="utf-8")
    pairs = sb.load_env_file(str(p))
    provider = next(k for k in sb.PROVIDERS if k in pairs)
    assert provider == "GEMINI_API_KEY"


def _http_error(code, reason, body: bytes):
    import io
    import urllib.error
    return urllib.error.HTTPError(
        "https://api.openai.com/v1/chat/completions", code, reason,
        hdrs=None, fp=io.BytesIO(body),
    )


def test_error_detail_extracts_message_and_param():
    # Review finding: the evaluator contract needs the 400 body's
    # message/param — reason alone is just "Bad Request".
    e = _http_error(400, "Bad Request", b'{"error": {"message": "Unsupported parameter: max_tokens", "param": "max_tokens", "type": "invalid_request_error"}}')
    assert sb.error_detail(e) == "Unsupported parameter: max_tokens (param: max_tokens)"


def test_error_detail_handles_non_json_and_is_bounded():
    e = _http_error(502, "Bad Gateway", b"<html>upstream error</html>" * 200)
    d = sb.error_detail(e)
    assert d.startswith("<html>upstream error")
    assert len(d) <= 200


def test_error_detail_never_raises_on_unreadable_body():
    import urllib.error
    e = urllib.error.HTTPError("https://api.openai.com/x", 400, "Bad Request", None, None)
    assert sb.error_detail(e) == ""


def test_status_line_keeps_contract_prefix():
    # Step-3 classification greps on the "http_<code>" prefix — the appended
    # detail must not break it.
    e = _http_error(400, "Bad Request", b'{"error": {"message": "Unsupported parameter"}}')
    detail = sb.error_detail(e)
    status = f"http_{e.code}: {e.reason}" + (f" — {detail}" if detail else "")
    assert status.startswith("http_400: Bad Request")
    assert "Unsupported parameter" in status


def test_auth_error_bodies_are_suppressed_entirely():
    # Review finding: an auth endpoint can echo the submitted credential in
    # its body, and 401/403 classification uses the code alone — so auth
    # bodies carry no detail at all.
    for code, reason in ((401, "Unauthorized"), (403, "Forbidden")):
        e = _http_error(code, reason, b'{"error": {"message": "bad key sk-live-SECRETKEY123"}}')
        assert sb.error_detail(e, ["sk-live-SECRETKEY123"]) == ""
        status = f"http_{e.code}: {e.reason}"
        assert "SECRETKEY123" not in status


def test_echoed_key_never_reaches_detail_or_status():
    # Review repro: FULL_SECRET_IN_DETAIL must be impossible. A 400 body that
    # echoes the key (JSON path) and a non-JSON fallback that echoes it are
    # both redacted inside error_detail itself.
    secrets = ["sk-live-SECRETKEY123"]
    e = _http_error(400, "Bad Request", b'{"error": {"message": "invalid key sk-live-SECRETKEY123 for model"}}')
    d = sb.error_detail(e, secrets)
    assert "SECRETKEY123" not in d and "***" in d
    e2 = _http_error(500, "Server Error", b"upstream said: sk-live-SECRETKEY123 rejected")
    d2 = sb.error_detail(e2, secrets)
    assert "SECRETKEY123" not in d2 and "***" in d2


def test_redact_strips_key_from_exception_status():
    # Review finding: http.client rejects an invalid header with the FULL
    # header value in the ValueError message — 'Bearer sk-live-KEY' would land
    # in the status JSONL, breaking the never-in-output promise.
    msg = "error: ValueError: Invalid header value b'Bearer sk-live-SECRET123\\rX'"
    assert "SECRET123" not in sb.redact(msg, ["sk-live-SECRET123"])
    assert "***" in sb.redact(msg, ["sk-live-SECRET123"])


def test_redact_tolerates_empty_secrets():
    assert sb.redact("error: boom", ["", None]) == "error: boom"


def test_source_provider_env_is_authoritative(tmp_path, monkeypatch):
    # Review finding: a file carrying several provider keys must not fall back
    # to dict-order guessing (OpenAI-first) — SOURCE_PROVIDER, the helper's
    # declared input, decides.
    pairs = {"OPENAI_API_KEY": "a", "ANTHROPIC_API_KEY": "b"}
    monkeypatch.setenv("SOURCE_PROVIDER", "anthropic")
    assert sb.pick_provider_key(pairs) == "ANTHROPIC_API_KEY"
    monkeypatch.setenv("SOURCE_PROVIDER", "openai")
    assert sb.pick_provider_key(pairs) == "OPENAI_API_KEY"
    # stated provider whose key is NOT in the file → hard None, never a guess
    monkeypatch.setenv("SOURCE_PROVIDER", "google")
    assert sb.pick_provider_key(pairs) is None
    monkeypatch.delenv("SOURCE_PROVIDER")
    assert sb.pick_provider_key(pairs) == "OPENAI_API_KEY"


def test_redact_catches_escaped_control_chars_in_exception_text():
    # Adjudicated finding: a raw CR inside the credential renders ESCAPED in
    # exception text (one control char -> backslash-r as two characters), so
    # literal replacement missed it and the key leaked in escaped form.
    secret = "sk-live-SECRET\rKEY123"
    escaped_msg = "error: ValueError: Invalid header value b'Bearer sk-live-SECRET\\rKEY123'"
    out = sb.redact(escaped_msg, [secret])
    assert "SECRET" not in out and "KEY123" not in out


def test_redact_catches_fragments_around_control_chars():
    # Even a partial echo of either side of the control char must not survive.
    secret = "sk-live-SECRET\nKEY123456"
    out = sb.redact("provider said sk-live-SECRET then KEY123456 rejected", [secret])
    assert "sk-live-SECRET" not in out and "KEY123456" not in out
