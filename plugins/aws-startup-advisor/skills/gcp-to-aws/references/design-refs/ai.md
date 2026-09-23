# AI/ML Services Design Rubric

**Applies to:** Vertex AI (traditional ML), Cloud Vision API, Cloud ML Engine (deprecated — now part of Vertex AI)

## LLM Routing

If the detected AI workload is LLM-based (generative models), load the source-specific design reference instead of this file:

- If `ai-workload-profile.json` → `summary.ai_source` = `"gemini"`: load `ai-gemini-to-bedrock.md`
- If `ai-workload-profile.json` → `summary.ai_source` = `"openai"`: load `ai-openai-to-bedrock.md`
- If `ai-workload-profile.json` → `summary.ai_source` = `"both"`: load both files
- If `ai-workload-profile.json` → `summary.ai_source` = `"other"` or absent, OR if the workload is traditional ML (custom models, Vision API, Speech API): use the SageMaker/Rekognition/Textract rubric below.

---

## Signals (Decision Criteria)

### Vertex AI (Endpoints / Models)

- **Custom model inference** → SageMaker Endpoints
- **Pre-built model APIs** → AWS APIs (Rekognition, Textract, Translate, etc.)
- **Batch prediction** → SageMaker Batch Transform

### Cloud Vision API

- **Image classification, OCR** → AWS Rekognition (images) or Textract (OCR)
- **Document understanding** → AWS Textract (more powerful for docs)

### Cloud Speech-to-Text

- **Audio/video transcription (batch or streaming)** → AWS Transcribe
- **Call center audio (with sentiment/topic detection needs)** → AWS Transcribe Call Analytics

### Document AI

- **Form/invoice/receipt/ID extraction** → AWS Textract (`AnalyzeExpense`, `AnalyzeID`, or `AnalyzeDocument` with `FORMS`/`TABLES` depending on document type)
- **General document OCR** → AWS Textract (`DetectDocumentText`)

### Cloud ML Engine (deprecated — legacy Terraform configs only)

- **Model training** → SageMaker (managed training jobs)
- **AutoML** → SageMaker Autopilot / Canvas

## 6-Criteria Rubric

Apply in order:

1. **Eliminators**: Does GCP config require AWS-unsupported features? If yes: use alternative
2. **Operational Model**: Managed (SageMaker) vs Custom (EC2 + training)?
   - Prefer managed
3. **User Preference**: From `preferences.json`: `design_constraints.cost_sensitivity` + `ai_constraints` (if present)
   - If cost-sensitive → check SageMaker Spot + Autopilot
4. **Feature Parity**: Does GCP config need model type unavailable in AWS?
   - Example: TensorFlow 2.x → SageMaker (supported)
5. **Cluster Context**: Are other compute resources running ML? Prefer SageMaker affinity
6. **Simplicity**: SageMaker endpoints (managed) > custom EC2 instances

## Examples

### Example 1: Vertex AI Endpoint (PyTorch model)

- GCP: `google_ai_platform_model` (model_name="image-classifier", framework=PYTORCH)
- Signals: Custom model inference, PyTorch
- Criterion 1 (Eliminators): PASS (PyTorch supported)
- Criterion 2 (Operational Model): SageMaker Endpoint (managed)
- → **AWS: SageMaker Endpoint (PyTorch container)**
- Confidence: `inferred`

### Example 2: Cloud Vision API

- GCP: `google_vision_api_call` (feature=TEXT_DETECTION, image_source=GCS)
- Signals: Pre-built API
- → **AWS: Textract (if document OCR) or Rekognition (if image classification)**
- Confidence: `inferred`

### Example 3: AutoML (image classification)

- GCP: `google_automl_image_classification_dataset`
- Signals: Training pipeline, classification
- Criterion 1 (Eliminators): PASS
- Criterion 2 (Operational Model): SageMaker Autopilot (managed)
- → **AWS: SageMaker Autopilot + Canvas (for low-code)**
- Confidence: `inferred`

### Example 4: Document AI (workload capability `document_extraction`)

- GCP: `documentai.process_document` call detected in app code
- Signals: Pre-built document extraction API, no custom model training
- → **AWS: Textract** (`AnalyzeExpense` for invoices/receipts, `AnalyzeID` for identity documents, `AnalyzeDocument` with `FORMS`/`TABLES` for general forms, `DetectDocumentText` for plain OCR — pick the closest match to the detected GCP processor type; default to `AnalyzeDocument` with `FORMS`/`TABLES` when the processor type can't be determined)
- Confidence: `inferred`

### Example 5: Cloud Speech-to-Text (workload capability `speech_transcription`)

- GCP: `speech.recognize` or `speech.long_running_recognize` call detected in app code
- Signals: Pre-built speech-to-text API
- → **AWS: Transcribe** (streaming → `StartStreamTranscription`; batch → `StartTranscriptionJob`)
- Confidence: `inferred`

## Output Schema

```json
{
  "gcp_type": "google_ai_platform_model",
  "gcp_address": "image-classifier-v2",
  "gcp_config": {
    "framework": "PYTORCH",
    "version": "1.9"
  },
  "aws_service": "SageMaker",
  "aws_config": {
    "endpoint_name": "image-classifier-v2",
    "instance_type": "ml.m5.large",
    "container_image": "pytorch:1.9"
  },
  "confidence": "inferred",
  "rationale": "Vertex AI custom model → SageMaker Endpoint (PyTorch supported)"
}
```
