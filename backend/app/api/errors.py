class ProviderNotSupportedError(Exception):
    """Raised when a provider string is unrecognized/unsupported."""
    pass


class MissingApiKeyError(Exception):
    """Raised when a required provider API key is missing from configuration."""
    pass
