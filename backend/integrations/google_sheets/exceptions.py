class GoogleSheetsError(RuntimeError):
    """Raised when a sheet can't be read (bad creds, not shared, missing tab…)."""
