"""Closed application provider registry; no plugins, arbitrary imports or fallbacks."""

from types import MappingProxyType

from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.compatible_provider import CompatibleProvider
from app.services.llm.contracts import ModelProfileSnapshot, Provider
from app.services.llm.openai_provider import OpenAIProvider

PROVIDERS = MappingProxyType(
    {
        Provider.OPENAI: OpenAIProvider,
        Provider.ANTHROPIC: AnthropicProvider,
        Provider.COMPATIBLE: CompatibleProvider,
    }
)


def create_provider(transport, profile, pinned, budget, **options):
    profile = ModelProfileSnapshot.model_validate(profile)
    selected = PROVIDERS.get(profile.provider)
    if selected is None or profile.protocol != selected.protocol:
        raise ValueError("unsupported provider/protocol")
    return selected(transport, profile, pinned, budget, **options)
