# Fix: bedrock-vision

## Symptom

You are migrating a Python service that calls a non-Bedrock vision API (Gemini `generate_content` with image input, OpenAI `gpt-4-vision`, or similar) to Amazon Bedrock, AND user-uploaded images flow through the service. Without normalization, Bedrock rejects non-standard images with `Image format not supported`.

## Fix

**Replaces**: Gemini/other AI vision API calls.

**How to use**:

1. Read the template file `references/bedrock-vision.py.template` (located in this skill's `references/` directory).
2. Copy the `_normalize_image()` function — this is critical, Bedrock rejects non-standard images.
3. Keep your existing `PROMPT` and `_parse_response()` logic from the original Gemini service.
4. Replace the API call pattern with the Bedrock `invoke_model` pattern from the template.
5. Add `pillow>=10.0.0` to `pyproject.toml` dependencies.

**Critical**: The `_normalize_image()` function is NON-OPTIONAL. Without it, user-uploaded images will fail with `Image format not supported`.

## Verification

After applying, the migrated service must:

1. Call `_normalize_image()` before passing image bytes to `invoke_model`.
2. Have `pillow>=10.0.0` declared in `pyproject.toml`.
3. Successfully process a non-JPEG/PNG user upload (e.g., a HEIC photo) without `Image format not supported`.
