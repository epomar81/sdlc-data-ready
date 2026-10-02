"""Shared application failures without provider-specific payloads."""


class StorySlicerError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(StorySlicerError):
    """Runtime configuration is missing or invalid."""


class InputError(StorySlicerError):
    """Requirement input cannot be loaded or validated."""


class ProviderError(StorySlicerError):
    """A provider request failed outside output validation."""


class SessionTimeoutError(StorySlicerError):
    """An attempt or the overall session exceeded its deadline."""


class ValidationExhaustedError(StorySlicerError):
    """Invalid model output exhausted the repair budget."""
