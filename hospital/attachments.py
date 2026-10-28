"""Attachment location and path validation."""
from pathlib import Path
from .errors import ValidationError

ATTACHMENTS_DIR = Path("hospital_attachments")
try:
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


def resolve_attachment_path(stored_path: str, root: Path = ATTACHMENTS_DIR) -> Path:
    """Resolve a stored attachment without allowing paths outside its root."""
    root_path = root.resolve()
    candidate = (root_path / stored_path).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValidationError("Attachment path is outside the attachment folder.") from exc
    return candidate
