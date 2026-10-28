"""One closed schema for account values; device and security values stay out."""

from copy import deepcopy
from typing import Any

VERSION = 1
MAX_REVISION = 9007199254740991

# Enum tuples also define defaults. No submitted value can become CSS, a URL,
# a model instruction, a permission, or an executable chart configuration.
OPTIONS = {
    "theme": ("opal", "light", "system"),
    "accent": ("pearl", "sage", "slate", "amber"),
    "density": ("comfortable", "compact"),
    "specks": ("subtle", "off"),
    "surface": ("solid", "depth"),
    "font": ("manrope", "system"),
    "recents_count": (10, 5, 20),
    "suggestions": (True, False),
    "timestamps": ("compact", "always", "hidden"),
    "wrap_code": (True, False),
    "initial_result_view": ("chart", "table"),
    "palette": ("categorical", "sequential", "diverging"),
    "legend": ("auto", "show", "hide"),
    "grid": ("subtle", "standard", "minimal"),
    "preserve_exploration": (True, False),
    "table_density": ("comfortable", "compact"),
    "table_page_size": (25, 10, 50),
    "precision": ("auto", "0", "2", "4", "6"),
    "expanded_summaries": (True, False),
    "locale": ("en-US", "en-GB"),
    "timezone": (
        "device",
        "UTC",
        "America/Chicago",
        "America/New_York",
        "America/Los_Angeles",
        "Europe/London",
    ),
    "date_style": ("medium", "short", "long"),
    "time_format": ("locale", "12", "24"),
}
SECTIONS = ("projects", "recents", "prompts")
DEFAULTS = {key: values[0] for key, values in OPTIONS.items()}
DEFAULTS["sidebar_sections"] = list(SECTIONS)

CAPABILITIES = {
    "account_security": False,
    "notification_delivery": False,
    "private_data_export": False,
    "private_data_delete": False,
    "personal_instructions": False,
    "response_style": False,
    "response_language": False,
    "default_model": False,
    "interface_languages": ["en"],
}


def validate_values(value: Any, *, complete: bool) -> dict:
    """Reject the whole object before changing a draft or persisted record."""
    if type(value) is not dict or set(value) - set(DEFAULTS):
        raise ValueError("preferences_invalid")
    if complete and set(value) != set(DEFAULTS):
        raise ValueError("preferences_incomplete")
    for key, item in value.items():
        if key == "sidebar_sections":
            if (
                type(item) is not list
                or len(item) > len(SECTIONS)
                or any(type(part) is not str or part not in SECTIONS for part in item)
                or len(set(item)) != len(item)
            ):
                raise ValueError("preferences_invalid")
        else:
            choices = OPTIONS[key]
            if type(item) is not type(choices[0]) or item not in choices:
                raise ValueError("preferences_invalid")
    return {**deepcopy(DEFAULTS), **deepcopy(value)}
