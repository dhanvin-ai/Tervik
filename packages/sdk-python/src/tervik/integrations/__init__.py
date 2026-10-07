"""Framework integrations. All duck-typed: the framework is never imported."""
from .anthropic import instrument_anthropic
from .langchain import TervikCallbackHandler
from .openai import instrument_openai

__all__ = ["TervikCallbackHandler", "instrument_anthropic", "instrument_openai"]
