"""Tests for the OpenAI reasoning-effort capability registry."""

from app.utils.openai_reasoning import resolve_reasoning_capability


def test_known_reasoning_model_returns_documented_options_and_default():
    capability = resolve_reasoning_capability("gpt-5.1")
    assert capability.status == "supported"
    assert capability.options == ("none", "low", "medium", "high")
    assert capability.default == "none"


def test_option_order_matches_documentation_exactly():
    capability = resolve_reasoning_capability("gpt-5.6-sol")
    assert capability.options == ("none", "low", "medium", "high", "xhigh", "max")


def test_known_non_reasoning_model_is_unsupported():
    capability = resolve_reasoning_capability("gpt-4o")
    assert capability.status == "unsupported"
    assert capability.options == ()
    assert capability.default is None


def test_unknown_future_model_is_unknown_not_guessed():
    capability = resolve_reasoning_capability("gpt-9-nebula")
    assert capability.status == "unknown"
    assert capability.options == ()
    assert capability.default is None


def test_dated_snapshot_alias_resolves_to_its_canonical_entry():
    canonical = resolve_reasoning_capability("gpt-5.1")
    snapshot = resolve_reasoning_capability("gpt-5.1-2025-11-13")
    assert snapshot == canonical

    canonical_gpt5 = resolve_reasoning_capability("gpt-5")
    snapshot_gpt5 = resolve_reasoning_capability("gpt-5-2025-08-07")
    assert snapshot_gpt5 == canonical_gpt5


def test_similarly_prefixed_models_are_not_conflated():
    """gpt-5 and gpt-5.1 share a naming prefix but OpenAI documents different
    option sets and defaults for them — broad prefix inference would get
    this wrong, so the registry must resolve each independently."""
    gpt5 = resolve_reasoning_capability("gpt-5")
    gpt51 = resolve_reasoning_capability("gpt-5.1")
    assert gpt5.options != gpt51.options
    assert gpt5.default != gpt51.default
    assert "minimal" in gpt5.options
    assert "none" not in gpt5.options
    assert "none" in gpt51.options


def test_reasoning_model_unusable_via_chat_completions_is_unsupported_for_bridge():
    """gpt-5-pro is Responses-API only; Bridge only calls Chat Completions,
    so it must never be offered a reasoning selector it could not actually
    validate or use."""
    capability = resolve_reasoning_capability("gpt-5-pro")
    assert capability.status == "unsupported"


def test_empty_or_whitespace_model_id_is_unknown():
    assert resolve_reasoning_capability("").status == "unknown"
    assert resolve_reasoning_capability("   ").status == "unknown"


def test_o_series_models_do_not_offer_none():
    for model in ("o1", "o3", "o4-mini"):
        capability = resolve_reasoning_capability(model)
        assert capability.status == "supported"
        assert "none" not in capability.options
        assert capability.default == "medium"
