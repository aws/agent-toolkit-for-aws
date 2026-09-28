# AI/ML Services Design Rubric

**Applies to:** the non-OpenAI kinds of `Microsoft.CognitiveServices/accounts` (Azure AI
Vision, Document Intelligence, Speech, Language, Translator), `Microsoft.MachineLearningServices/*`
(Azure Machine Learning), and any traditional-ML workload detected in app code
(`image_analysis`, `document_extraction`, `speech_transcription`). This is the `ai_source:
"other"` / capability-routed rubric. It is the Azure port of gcp-to-aws's `ai.md`: the AWS
targets are identical (they do not depend on the source cloud); only the source-service
signals change.

> **Not for Azure OpenAI.** A `Microsoft.CognitiveServices/accounts` with `kind: OpenAI`, or an
> app-code workload whose `ai_source` is `azure_openai`/`openai`/`anthropic`, routes to the
> Bedrock guides, not here — see § LLM Routing.

## LLM Routing

If the detected AI workload is LLM-based (generative text/chat), load the source-specific
Bedrock guide instead of this file:

- `summary.ai_source == "azure_openai"` or `"openai"` → `vendored/ai/ai-openai-to-bedrock.md`
  (source-cloud-agnostic — its header explicitly serves Azure OpenAI, since the Bedrock target
  does not depend on which endpoint served the calls).
- `summary.ai_source == "anthropic"` → `vendored/ai/ai-anthropic-to-bedrock.md`.
- `summary.ai_source == "both"` → both of the above.
- `summary.ai_source == "other"` or absent, OR the workload is traditional ML (Vision,
  Document Intelligence, Speech, Language, Translator, custom Azure ML models) → use the
  SageMaker/Rekognition/Textract/Comprehend/Transcribe/Translate/Polly rubric below.

A generative `ai_source` does not exempt a traditional-AI workload: an `azure_openai` codebase
that also calls Azure AI Document Intelligence needs BOTH the OpenAI guide (for its GPT
workload) and this file (for the Document Intelligence workload). Capability is evaluated
per workload.

## Signals (Decision Criteria)

### Azure Machine Learning (`Microsoft.MachineLearningServices/workspaces`, online/batch endpoints, jobs)

- **Custom model inference (online endpoint)** → SageMaker Endpoints.
- **Pre-built / catalog model APIs** → the AWS AI API for that capability (Rekognition,
  Textract, Comprehend, Transcribe, Translate, Polly).
- **Batch scoring / batch endpoint** → SageMaker Batch Transform.
- **Training jobs, AutoML** → SageMaker managed training / SageMaker Autopilot.

### Azure AI Vision (Computer Vision) — `kind: ComputerVision`

- **Image classification, object/label detection, moderation, faces** → AWS Rekognition.
- **OCR / read (printed or handwritten text in images)** → AWS Textract (`DetectDocumentText`)
  for document OCR; Rekognition `DetectText` for scene text in images.

### Azure AI Document Intelligence / Form Recognizer — `kind: FormRecognizer`

- **Form / invoice / receipt / ID / business-card extraction** → AWS Textract
  (`AnalyzeExpense` for invoices/receipts, `AnalyzeID` for identity documents, or
  `AnalyzeDocument` with `FORMS`/`TABLES` for general structured extraction).
- **General document OCR** → AWS Textract (`DetectDocumentText`).
- **Custom/trained document models** → Textract custom queries, or SageMaker if the model is
  a genuinely custom vision model rather than a Document-Intelligence template.

### Azure AI Speech — `kind: SpeechServices`

- **Audio/video transcription (batch or streaming)** → AWS Transcribe
  (`StartTranscriptionJob` / `StartStreamTranscription`).
- **Call-centre audio with sentiment/topic needs** → AWS Transcribe Call Analytics.
- **Text-to-speech / voice synthesis** → AWS Polly (a new, separate line item — Azure bundles
  STT and TTS under one Speech resource; on AWS they are Transcribe and Polly respectively).

### Azure AI Language (Text Analytics) — `kind: TextAnalytics`

- **Sentiment, key-phrase, entity/PII recognition, language detection, summarization** → AWS
  Comprehend (or Comprehend Medical for PHI-bearing clinical text).
- **Custom text classification / custom NER** → Comprehend custom classifiers/entity
  recognizers, or SageMaker for a fully custom model.

### Azure AI Translator — `kind: TextTranslation`

- **Text translation** → AWS Translate.

## 6-Criteria Rubric

Apply in order, first match wins (the rubric selects a SERVICE; sizing is post-selection):

1. **Eliminators:** does the Azure config require an AWS-unsupported feature? If yes, note the
   gap and pick the closest alternative (or defer).
2. **Operational Model:** managed (SageMaker / the managed AWS AI APIs) vs custom (EC2 +
   training). Prefer managed.
3. **User Preference:** `preferences.json` → `design_constraints.cost_optimization` +
   `ai_constraints` (if present). Cost-sensitive → prefer SageMaker Spot + Autopilot, and the
   pay-per-call AI APIs over always-on endpoints.
4. **Feature Parity:** does the Azure config need a model type unavailable on AWS? (e.g. a
   custom framework — most map to SageMaker containers.)
5. **Cluster Context:** are other resources in the cluster running ML on SageMaker? Prefer
   SageMaker affinity.
6. **Simplicity:** managed AI APIs / SageMaker endpoints over custom EC2.

## Right-Sizing

Post-selection, structurally parallel to the compute rubric's `## Right-Sizing`. The managed
AWS AI APIs (Rekognition, Textract, Comprehend, Transcribe, Translate, Polly) are pay-per-call
and carry no instance size — set `sizing_provenance` accordingly and do not invent a capacity.
A SageMaker endpoint DOES carry an instance type: size it from observed traffic when
utilization exists (`sizing_provenance: measured`), else state a dev-tier default
(`ml.m5.large`) with `sizing_provenance: model_prior`.

## CPU Architecture

Not applicable to the managed AI APIs. A SageMaker endpoint follows the skill's `x86_64`
default unless a Graviton-supported container image and a stated preference both hold.

## Examples

### Example 1 — Azure ML online endpoint (custom PyTorch model) → SageMaker Endpoint

`azure_type: Microsoft.MachineLearningServices/workspaces/onlineEndpoints`,
`azure_config: { framework: "PyTorch", version: "2.1" }` → `aws_service: "SageMaker"`,
`aws_config: { endpoint_name: "...", instance_type: "ml.m5.large", container_image:
"pytorch:2.1" }`, `confidence: inferred`, `sizing_provenance: model_prior`,
`rationale: "Azure ML custom online endpoint → SageMaker Endpoint (PyTorch supported)"`.

### Example 2 — Azure AI Vision (image labelling) → Rekognition (capability `image_analysis`)

`azure_type: Microsoft.CognitiveServices/accounts` (`kind: ComputerVision`) →
`target_aws_service: "rekognition"`, `target_bedrock_model: null`, `confidence: inferred`,
`honest_assessment: "not_applicable"`, `rationale: "Azure AI Vision label/object detection →
Rekognition DetectLabels"`.

### Example 3 — Azure AI Document Intelligence (invoices) → Textract (capability `document_extraction`)

`kind: FormRecognizer`, invoice/receipt extraction → `target_aws_service: "textract"`,
`aws_config: { api: "AnalyzeExpense" }`, `confidence: inferred`,
`honest_assessment: "not_applicable"`.

### Example 4 — Azure AI Language (sentiment/entities) → Comprehend

`kind: TextAnalytics` → `target_aws_service: "comprehend"`, `confidence: inferred`,
`honest_assessment: "not_applicable"`, `rationale: "Azure AI Language sentiment + entity
recognition → Amazon Comprehend"`. This section has no gcp analogue — it is net-new for Azure.

### Example 5 — Azure AI Speech (transcription) → Transcribe (capability `speech_transcription`)

`kind: SpeechServices`, batch transcription → `target_aws_service: "transcribe"`,
`confidence: inferred`, `honest_assessment: "not_applicable"`. If the resource also does
synthesis, emit a SECOND `design_block` mapping the TTS capability to Polly.

## Output Schema

Each mapped resource contributes a `design_blocks[]` row (see
`references/shared/schema-design-aws-ai.md`). Traditional-AI workloads set
`target_aws_service` (one of `textract`, `rekognition`, `comprehend`, `transcribe`,
`translate`, `polly`, `sagemaker`), leave `target_bedrock_model: null`, and carry
`honest_assessment: "not_applicable"` — they are feature/service swaps, not Bedrock model
migrations. Confidence is `inferred` (or `measured` when utilization backed a SageMaker size).
`azure_id` / `azure_type` / `azure_config` carry the source facts.
