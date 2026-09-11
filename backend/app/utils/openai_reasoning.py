"""Bridge-side registry of OpenAI reasoning-effort capabilities.

Neither the OpenAI model-list response nor the installed `openai` SDK expose
any reasoning-capability metadata (a `Model` object returned by
`client.models.list()` carries only `id`/`created`/`object`/`owned_by`, and
the SDK's `ReasoningEffort` type is just the static value-shape enum, not a
per-model capability map). There is no live endpoint Bridge can query to
learn which models support configurable reasoning, which values they accept,
or their documented default.

This module is therefore the one hand-maintained source of truth for that
information, verified against OpenAI's official model documentation at
https://developers.openai.com/api/docs/models/<model-id> and
https://developers.openai.com/api/docs/guides/reasoning (checked 2026-09).
Update the tables below when OpenAI ships a new model or changes an
existing model's reasoning contract. Do not derive an entry from a model-id
prefix/family match at runtime — OpenAI documents materially different
option sets and defaults for models in the same naming family (e.g.
`gpt-5.1` defaults to `none` and does not offer `minimal`; `gpt-5` has no
`none` option and defaults to `medium`; `gpt-5-pro` is Responses-API-only
and unusable through the Chat Completions endpoint Bridge uses at all).
A model id with no table entry resolves to status="unknown" rather than a
guessed capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReasoningStatus = Literal["supported", "unsupported", "unknown"]


@dataclass(frozen=True)
class ReasoningCapability:
    """Normalized OpenAI reasoning-effort capability for one exact model id.

    status:
        "supported"   — reasoning_effort is configurable on Chat Completions
                         for this model; `options`/`default` are populated.
        "unsupported" — documentation confirms this model does not accept
                         reasoning_effort on Chat Completions (either because
                         it isn't a reasoning model, or because reasoning is
                         only configurable through the Responses API).
        "unknown"     — Bridge's registry has no verified entry for this
                         model id yet. Not the same as "unsupported": the
                         model may well support reasoning, Bridge just does
                         not have a documented option set/default for it.
    options: exact allowed `reasoning_effort` values, in documented order.
    default: the model's documented default `reasoning_effort` value.
    """

    status: ReasoningStatus
    options: tuple[str, ...] = ()
    default: str | None = None


_UNSUPPORTED = ReasoningCapability(status="unsupported")
_UNKNOWN = ReasoningCapability(status="unknown")

# Canonical model id -> capability, each verified against the cited OpenAI
# documentation page. Only models Bridge can reach through the Chat
# Completions API are relevant here.
_CAPABILITIES: dict[str, ReasoningCapability] = {
    # -- GPT-5.1 --------------------------------------------------------
    # https://developers.openai.com/api/docs/models/gpt-5.1
    # Defaults to `none` (no reasoning); only pre-gpt-5.1-family model that
    # offers `none` without also offering `xhigh`/`max`.
    "gpt-5.1": ReasoningCapability(
        "supported", ("none", "low", "medium", "high"), "none"
    ),
    # -- GPT-5.4 ----------------------------------------------------------
    # https://developers.openai.com/api/docs/models/gpt-5.4
    "gpt-5.4": ReasoningCapability(
        "supported", ("none", "low", "medium", "high", "xhigh"), "none"
    ),
    # -- GPT-5.5 ----------------------------------------------------------
    # https://developers.openai.com/api/docs/guides/reasoning (GPT-5.5 section)
    "gpt-5.5": ReasoningCapability(
        "supported", ("none", "low", "medium", "high", "xhigh", "max"), "medium"
    ),
    # -- GPT-5.6 family (Sol / Terra / Luna) -------------------------------
    # https://developers.openai.com/api/docs/models/gpt-5.6-sol
    # https://developers.openai.com/api/docs/models/gpt-5.6-terra
    "gpt-5.6-sol": ReasoningCapability(
        "supported", ("none", "low", "medium", "high", "xhigh", "max"), "medium"
    ),
    "gpt-5.6-terra": ReasoningCapability(
        "supported", ("none", "low", "medium", "high", "xhigh", "max"), "medium"
    ),
    # https://developers.openai.com/api/docs/models/gpt-5.6-luna — Luna's own
    # page does not separately restate Chat Completions support, but OpenAI
    # documents Sol/Terra/Luna as one generation sharing the same reasoning
    # contract, and both siblings explicitly confirm Chat Completions support
    # for reasoning_effort with these same values/default.
    "gpt-5.6-luna": ReasoningCapability(
        "supported", ("none", "low", "medium", "high", "xhigh", "max"), "medium"
    ),
    # -- GPT-5 base family --------------------------------------------------
    # https://developers.openai.com/api/docs/models/gpt-5
    "gpt-5": ReasoningCapability(
        "supported", ("minimal", "low", "medium", "high"), "medium"
    ),
    # -- o-series -----------------------------------------------------------
    # Individual o1/o3/o4-mini doc pages link to the reasoning guide rather
    # than restate values. Per OpenAI's documented general rule for "models
    # before gpt-5.1" (carried in the openai SDK's own parameter description,
    # openai/types/shared/reasoning.py: "All models before gpt-5.1 default to
    # `medium` reasoning effort, and do not support `none`") these three
    # long-shipped reasoning models accept low/medium/high with no `none`.
    "o1": ReasoningCapability("supported", ("low", "medium", "high"), "medium"),
    "o3": ReasoningCapability("supported", ("low", "medium", "high"), "medium"),
    "o4-mini": ReasoningCapability("supported", ("low", "medium", "high"), "medium"),
    # -- Reasoning models NOT usable through Chat Completions ---------------
    # https://developers.openai.com/api/docs/models/gpt-5-pro — Responses API
    # only; not available through the Chat Completions endpoint Bridge uses
    # at all, so there is no reasoning_effort Bridge can ever send for it.
    "gpt-5-pro": _UNSUPPORTED,
    # https://developers.openai.com/api/docs/guides/reasoning — GPT-6 Astra's
    # reasoning.effort is documented as a Responses-API parameter; Chat
    # Completions does not accept reasoning_effort for this model.
    "gpt-6-astra": _UNSUPPORTED,
    # -- Known non-reasoning chat models --------------------------------
    # https://developers.openai.com/api/docs/models/gpt-4o
    "gpt-4o": _UNSUPPORTED,
    "gpt-4o-mini": _UNSUPPORTED,
    "gpt-4-turbo": _UNSUPPORTED,
    "gpt-4.1": _UNSUPPORTED,
    "gpt-4.1-mini": _UNSUPPORTED,
    "gpt-4.1-nano": _UNSUPPORTED,
    "gpt-3.5-turbo": _UNSUPPORTED,
}

# Dated/versioned snapshot ids that OpenAI documents as sharing the exact
# capability contract of the canonical id they point to.
_SNAPSHOT_ALIASES: dict[str, str] = {
    "gpt-5.1-2025-11-13": "gpt-5.1",
    "gpt-5-2025-08-07": "gpt-5",
}


def resolve_reasoning_capability(model: str) -> ReasoningCapability:
    """Look up the reasoning-effort capability for an exact OpenAI model id.

    Table-driven only — see module docstring for why prefix/family
    inference is deliberately not used. Unrecognized model ids (including
    models newer than this table) return status="unknown", never a guessed
    "supported" or "unsupported".
    """
    normalized = (model or "").strip()
    canonical = _SNAPSHOT_ALIASES.get(normalized, normalized)
    return _CAPABILITIES.get(canonical, _UNKNOWN)
