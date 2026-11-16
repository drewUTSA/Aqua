"""Compatibility API for the original offline companion qualification contracts."""

from companion.choices import validate_choices as validate_choices
from companion.context import assemble_context as assemble_context
from companion.data_contract import (
    BINDING as BINDING,
    MAX_AGE_SECONDS as MAX_AGE_SECONDS,
    MAX_BLOCKS as MAX_BLOCKS,
    MAX_CONTEXT_BYTES as MAX_CONTEXT_BYTES,
    MAX_INPUT_BYTES as MAX_INPUT_BYTES,
    PREFERENCES as PREFERENCES,
    TOOLS as TOOLS,
    CompanionDenied as CompanionDenied,
    Context as Context,
    _binding as _binding,
    _encode as _encode,
    _identifier as _identifier,
    _load as _load,
    _payload as _payload,
    _text as _text,
    _unique as _unique,
)
