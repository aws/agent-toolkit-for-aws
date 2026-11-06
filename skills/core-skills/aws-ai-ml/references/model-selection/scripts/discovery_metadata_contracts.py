"""Canonical discovery-metadata values for public-Hub Search requests.

The Hub producer normalizes every open-weight model's discovery fields to one
spelling per value before publishing. This module carries the same
vocabularies and alias maps so Sherpa can build an exact ``Metadata.*`` Search
value from a customer's request even when no model kept that value as a
``ListHubContents`` keyword.

Why the port exists. The catalog snapshot learns values from
``HubContentSearchKeywords``, and the Hub writes at most 50 keywords per
model. A value carried only by models whose keyword slots ran out (eight
documents list Kyrgyz; none has an ``@language:kyrgyz`` keyword) has no
keyword anywhere, so snapshot resolution cannot see it. The contract is the
second source: a value the snapshot does not know is resolved here and sent to
Search, which decides whether any model matches. An empty Search result is a
real empty result, not a validation failure.

Source of truth: ``aws/sagemaker-model-hub``,
``src/sagemakermodelhub/content_generation/metadata/sdk/discovery_metadata_contracts.py``
and the ``DataType``, ``ProblemType``, and ``EulaType`` enums, at the commit in
``CONTRACT_SOURCE_COMMIT``. Refresh by copying the vocabularies and alias maps
from that file at the new commit, updating the commit constant, and running
``test_discovery_metadata_contracts.py``, which freezes every vocabulary so a
change is deliberate.

Dependencies: Python standard library only.
"""

import re
import unicodedata
from dataclasses import dataclass

CONTRACT_SOURCE_COMMIT = "2017f466"

# Resolution statuses. The first three are sendable; the last two need the user.
CANONICAL = "canonical"  # one or more values of a closed vocabulary
DERIVED = "derived"  # a rule-based field produced its display form
OPEN = "open"  # the field has no vocabulary; send the request as given
AMBIGUOUS = "ambiguous"  # several canonical values, or a code-shaped language
UNKNOWN = "unknown"  # a closed vocabulary with no match

# --- Closed vocabularies -----------------------------------------------------

DATA_TYPE_VALUES = frozenset(
    {"Multimodal", "vision", "text", "audio", "tabular", "biology"}
)
INPUT_MODALITY_VALUES = frozenset(
    {"Audio", "Image", "Protein", "Tabular", "Text", "Time series", "Video"}
)
OUTPUT_MODALITY_VALUES = frozenset(
    {"Audio", "Embeddings", "Forecasts", "Image", "Structure", "Tabular", "Text", "Video"}
)
CONTEXT_WINDOW_VALUE_ORDER = ("<4K", "4K-8K", "8K-32K", "32K-128K", ">128K")
CONTEXT_WINDOW_VALUES = frozenset(CONTEXT_WINDOW_VALUE_ORDER)
MODEL_SIZE_VALUE_ORDER = ("<1B", "1B-10B", "10B-70B", "70B-100B", ">100B")
MODEL_SIZE_VALUES = frozenset(MODEL_SIZE_VALUE_ORDER)
MODEL_TYPE_VALUES = frozenset({"OPEN_WEIGHTS", "PROPRIETARY"})
LICENSE_VALUES = frozenset(
    {
        "Alexa Model License",
        "Apache-2.0",
        "BSD",
        "BigCode Open RAIL-M v1",
        "BigScience BLOOM RAIL 1.0",
        "BigScience RAIL License",
        "CreativeML Open RAIL++-M",
        "CreativeML Open RAIL-M",
        "Databricks Open Model License",
        "Falcon LLM License",
        "GLM-5.3 License",
        "Kanana License Agreement",
        "Kimi K3 License",
        "Llama 2 Community License",
        "Llama 3 Community License",
        "Llama 3.1 Community License",
        "Llama 3.2 Community License",
        "Llama 3.3 Community License",
        "Llama 4 Community License",
        "Llama Community License",
        "MIT",
        "Muse Model License",
        "NVIDIA License",
        "NVIDIA Open Model Agreement",
        "OpenMDW License Agreement",
    }
)
# Open-weight Task values (the producer's ProblemType display names).
# Proprietary models publish a free-text Task that is not under contract;
# every model keeps its task keyword, so the snapshot resolves those.
TASK_VALUES = frozenset(
    {
        "Audio Classification",
        "Automatic Speech Recognition",
        "Decision",
        "Fill-Mask",
        "Image Classification",
        "Image Segmentation",
        "Image-Text-to-Image",
        "Image-Text-to-Text",
        "Image-to-Image",
        "Image-to-Text",
        "Object Detection",
        "Protein Structure Prediction",
        "Question Answering",
        "Reasoning",
        "Sentence Similarity",
        "Tabular Classification",
        "Tabular Regression",
        "Text Classification",
        "Text Embedding",
        "Text Generation",
        "Text Summarization",
        "Text-to-Image",
        "Text-to-Speech",
        "Text-to-Video",
        "Text2Text Generation",
        "Time Series Forecasting",
        "Token Classification",
        "Translation",
        "Zero-Shot Classification",
    }
)

# --- Alias maps (non-canonical spelling -> canonical value) ------------------

LICENSE_NAME_ALIASES = {
    "Apache 2.0": "Apache-2.0",
    "BigScience RAIL": "BigScience RAIL License",
    "CreativeML OpenRAIL-M": "CreativeML Open RAIL-M",
    "CreativeML OpenRAIL++-M": "CreativeML Open RAIL++-M",
    "Llama 2 Community": "Llama 2 Community License",
    "Llama 3 Community": "Llama 3 Community License",
    "Llama 3.1 Community": "Llama 3.1 Community License",
    "Llama 3.2 Community": "Llama 3.2 Community License",
    "bigcode-openrail-m": "BigCode Open RAIL-M v1",
    "modified-mit": "MIT",
}
# English names the producer's language data resolves to a newer display name.
LANGUAGE_NAME_ALIASES = {
    "Bengali": "Bangla",
    "Ossetian": "Ossetic",
    "Yi": "Sichuan Yi",
}

# Sherpa's selectable size buckets map onto the producer's ModelSize buckets.
# Sherpa's ``<=10b`` spans two producer buckets; the other three align.
SIZE_BUCKET_CANONICAL_VALUES = {
    "<=10b": ("<1B", "1B-10B"),
    "11b-70b": ("10B-70B",),
    "71b-100b": ("70B-100B",),
    ">100b": (">100B",),
}

# Code-shaped values require interpretation that this portable skill contract
# deliberately leaves to the user. ``so`` has two concrete interpretations.
_LANGUAGE_TAG_PATTERN = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")
_AMBIGUOUS_SHORT_LANGUAGE_VALUES = {
    "so": ("Somali", "So (Democratic Republic of Congo)"),
}
# Canonical English display names of at most three characters known to the
# producer's language data at CONTRACT_SOURCE_COMMIT, plus the reviewer-found
# Twi and Fon names. Check these before interpreting the same token as a code.
_SHORT_LANGUAGE_NAMES = {
    "asu": "Asu",
    "ewe": "Ewe",
    "fon": "Fon",
    "ga": "Ga",
    "ido": "Ido",
    "jju": "Jju",
    "lao": "Lao",
    "rwa": "Rwa",
    "twi": "Twi",
    "vai": "Vai",
}
# Producer display names whose punctuation or internal capitalization cannot be
# reconstructed safely by capitalizing words. Unknown apostrophe names ask for
# clarification rather than issuing an exact Search that cannot match.
_SPECIAL_LANGUAGE_DISPLAY_NAMES = {
    "k'iche'": "Kʼicheʼ",
    "kʼicheʼ": "Kʼicheʼ",
    "n'ko": "N’Ko",
    "n’ko": "N’Ko",
}
_LANGUAGE_APOSTROPHES = frozenset("'’ʼ")
_LANGUAGE_NAME_PUNCTUATION = frozenset(" -'’ʼ()")

# Sherpa constraint key -> (Hub document field, vocabulary, aliases)
_CLOSED_CONTRACTS = {
    "data_type": ("DataType", DATA_TYPE_VALUES, {}),
    "input_modality": ("InputModalities", INPUT_MODALITY_VALUES, {}),
    "output_modality": ("OutputModalities", OUTPUT_MODALITY_VALUES, {}),
    "context_window": ("ContextWindow", CONTEXT_WINDOW_VALUES, {}),
    "license": ("License", LICENSE_VALUES, LICENSE_NAME_ALIASES),
    "task": ("Task", TASK_VALUES, {}),
    "model_type": ("ModelTypes", MODEL_TYPE_VALUES, {}),
}
_RULE_BASED_FIELDS = {"language": "Languages"}
_OPEN_FIELDS = {"provider": "Provider"}
_CLOSED_VALUE_ORDERS = {
    "context_window": CONTEXT_WINDOW_VALUE_ORDER,
    "data_type": ("text", "vision", "audio", "Multimodal", "tabular", "biology"),
    "model_type": ("OPEN_WEIGHTS", "PROPRIETARY"),
}

_SEPARATOR_PATTERN = re.compile(r"[\s,._-]+")


@dataclass(frozen=True)
class ContractResolution:
    """How one requested value maps onto the producer contract.

    ``values`` are exact document values to send when ``resolved`` is true.
    ``canonical_values`` lists the whole vocabulary of a closed field so a
    caller can offer the choices back to the user; it is empty for rule-based
    and open fields.
    """

    key: str
    requested_value: str
    status: str
    document_field: str
    values: tuple = ()
    canonical_values: tuple = ()

    @property
    def resolved(self):
        return self.status in (CANONICAL, DERIVED, OPEN)


def fold_value(value):
    """Return a comparison key: NFKC, case-folded, separators collapsed.

    Mirrors the producer's ``fold_value`` so ``Apache_2.0``, ``apache 2.0``,
    and ``APACHE-2.0`` compare equal without changing any stored value.
    """
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    # Strip again: a leading or trailing separator becomes a space above.
    return _SEPARATOR_PATTERN.sub(" ", normalized).strip()


def _resolve_closed(key, requested_value, match_mode):
    document_field, vocabulary, aliases = _CLOSED_CONTRACTS[key]
    folded = fold_value(requested_value)
    canonical_values = tuple(
        _CLOSED_VALUE_ORDERS.get(key, sorted(vocabulary, key=str.lower))
    )

    def resolution(status, values=()):
        return ContractResolution(
            key=key,
            requested_value=requested_value,
            status=status,
            document_field=document_field,
            values=tuple(values),
            canonical_values=canonical_values,
        )

    for alias, canonical in aliases.items():
        if fold_value(alias) == folded:
            return resolution(CANONICAL, [canonical])

    exact = sorted((v for v in vocabulary if fold_value(v) == folded), key=str.lower)
    if len(exact) == 1:
        return resolution(CANONICAL, exact)
    if len(exact) > 1:
        return resolution(AMBIGUOUS, exact)

    if match_mode == "substring":
        # A substring request OR-s every value it covers, the same semantics
        # the snapshot path applies to ``license:apache`` or ``task:class``.
        matches = {v for v in vocabulary if folded in fold_value(v)}
        matches.update(
            canonical for alias, canonical in aliases.items() if folded in fold_value(alias)
        )
        if matches:
            return resolution(CANONICAL, sorted(matches, key=str.lower))

    return resolution(UNKNOWN)


def _language_resolution(requested_value, status, values=()):
    return ContractResolution(
        key="language",
        requested_value=requested_value,
        status=status,
        document_field=_RULE_BASED_FIELDS["language"],
        values=tuple(dict.fromkeys(values)),
    )


def _is_language_name(value):
    """Return whether a value can be normalized as a full language name."""
    return bool(value) and all(
        character.isalpha() or character in _LANGUAGE_NAME_PUNCTUATION
        for character in value
    )


def _capitalize_language_words(value):
    """Capitalize each word without changing letters after punctuation."""
    capitalized = []
    for word in value.strip().split(" "):
        first_letter = next(
            (index for index, character in enumerate(word) if character.isalpha()),
            None,
        )
        if first_letter is None:
            capitalized.append(word)
            continue
        capitalized.append(
            word[:first_letter]
            + word[first_letter].upper()
            + word[first_letter + 1 :]
        )
    return " ".join(capitalized)


def _offered_language_values():
    """Return every exact value this resolver can present to the user."""
    values = list(LANGUAGE_NAME_ALIASES.values())
    values.extend(_SHORT_LANGUAGE_NAMES.values())
    values.extend(_SPECIAL_LANGUAGE_DISPLAY_NAMES.values())
    for candidates in _AMBIGUOUS_SHORT_LANGUAGE_VALUES.values():
        values.extend(candidates)
    return tuple(dict.fromkeys(values))


def _resolve_language(requested_value):
    folded = fold_value(requested_value)

    for alias, canonical in LANGUAGE_NAME_ALIASES.items():
        if fold_value(alias) == folded:
            return _language_resolution(requested_value, CANONICAL, [canonical])

    for spelling, canonical in _SPECIAL_LANGUAGE_DISPLAY_NAMES.items():
        if fold_value(spelling) == folded:
            return _language_resolution(requested_value, CANONICAL, [canonical])

    # A value offered by an earlier clarification must round-trip byte for byte.
    # This check runs before title-casing, which would incorrectly turn the
    # connector in ``So (Democratic Republic of Congo)`` into ``Of``.
    for canonical in _offered_language_values():
        if fold_value(canonical) == folded:
            return _language_resolution(requested_value, CANONICAL, [canonical])

    if requested_value in _AMBIGUOUS_SHORT_LANGUAGE_VALUES:
        return _language_resolution(
            requested_value,
            AMBIGUOUS,
            _AMBIGUOUS_SHORT_LANGUAGE_VALUES[requested_value],
        )

    # A short ISO/BCP 47 shape is not a full language name. Ask rather than
    # guess which language the customer meant. The LLM returns with a full name
    # (for example ``so`` -> Somali), which this function then normalizes.
    if _LANGUAGE_TAG_PATTERN.fullmatch(requested_value):
        return _language_resolution(requested_value, UNKNOWN)

    if not _is_language_name(requested_value):
        return _language_resolution(requested_value, UNKNOWN)
    if any(character in _LANGUAGE_APOSTROPHES for character in requested_value):
        return _language_resolution(requested_value, UNKNOWN)

    # Public-Hub language metadata uses English display names. Constraint input
    # is lower-cased before it reaches this contract, so capitalizing the first
    # alphabetic character of each space-separated word restores names such as
    # Somali and Haitian Creole without mangling letters after punctuation.
    # Values with nontrivial internal casing are handled above or rejected.
    return _language_resolution(
        requested_value, DERIVED, [_capitalize_language_words(requested_value)]
    )


def resolve_search_values(key, requested_value, match_mode="exact"):
    """Resolve one requested value to the exact document value(s) to search.

    ``match_mode`` is ``"exact"`` or ``"substring"`` and mirrors how the
    snapshot path matches the same constraint key. Raises ``KeyError`` for a
    key the contract does not cover (``size`` has its own bucket map; ``name``,
    ``bedrock``, and ``customization`` are not discovery values).
    """
    if key in _CLOSED_CONTRACTS:
        return _resolve_closed(key, requested_value, match_mode)
    if key in _RULE_BASED_FIELDS:
        return _resolve_language(requested_value)
    if key in _OPEN_FIELDS:
        return ContractResolution(
            key=key,
            requested_value=requested_value,
            status=OPEN,
            document_field=_OPEN_FIELDS[key],
            values=(requested_value,),
        )
    raise KeyError(f"No discovery metadata contract covers constraint key {key!r}")


def canonical_size_values(size_bucket):
    """Return the producer ModelSize values inside one Sherpa size bucket."""
    return SIZE_BUCKET_CANONICAL_VALUES.get(size_bucket, ())


def canonical_values_for_requests():
    """Return the closed vocabularies, keyed like ``available_values``.

    Values keep the document's casing; constraint requests are matched
    case-insensitively, so ``context_window:8k-32k`` reaches ``8K-32K``.
    Sizes are Sherpa's selectable buckets, which the adapter expands to the
    producer's ModelSize values.
    """
    return {
        "tasks": sorted(TASK_VALUES, key=str.lower),
        "data_types": sorted(DATA_TYPE_VALUES, key=str.lower),
        "input_modalities": sorted(INPUT_MODALITY_VALUES, key=str.lower),
        "output_modalities": sorted(OUTPUT_MODALITY_VALUES, key=str.lower),
        "sizes": list(SIZE_BUCKET_CANONICAL_VALUES),
        "licenses": sorted(LICENSE_VALUES, key=str.lower),
        "context_windows": list(CONTEXT_WINDOW_VALUE_ORDER),
        "model_types": sorted(MODEL_TYPE_VALUES),
    }


def canonical_rules_for_requests():
    """Describe the fields that have a rule instead of a vocabulary."""
    aliases = ", ".join(f"{k} -> {v}" for k, v in LANGUAGE_NAME_ALIASES.items())
    return {
        "languages": (
            "English language names as the Hub publishes them, for example "
            "Somali or Haitian Creole. A name the catalog does not list is still "
            "searched. Code-shaped values must be clarified to a full name "
            "unless they match a known short name such as Lao, Ewe, or Ido. "
            f"Aliases: {aliases}."
        ),
        "providers": (
            "Any provider name. A name the catalog does not list is searched in "
            "every producer casing."
        ),
    }
