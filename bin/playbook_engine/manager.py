"""Playbook Manager — storage, matching, promotion, versioning."""

import re
import shutil
from pathlib import Path
from typing import Optional
from models import Playbook

_VALID_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _validate_playbook_id(playbook_id: str) -> str:
    """Validate playbook_id is safe for use as a filename. Raises ValueError on bad input."""
    if not playbook_id or not _VALID_ID_RE.match(playbook_id) or ".." in playbook_id:
        raise ValueError(f"Invalid playbook ID: {playbook_id!r} (must be lowercase alphanumeric with hyphens)")
    return playbook_id


class PlaybookManager:
    def __init__(self, playbooks_dir: str):
        self.base = Path(playbooks_dir)
        self.approved_dir = self.base
        self.drafts_dir = self.base / "drafts"
        self.archive_dir = self.base / "archive"
        for d in [self.approved_dir, self.drafts_dir, self.archive_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def save(self, playbook: Playbook, archive_previous: bool = False) -> str:
        _validate_playbook_id(playbook.id)
        path = self.approved_dir / f"{playbook.id}.yml"
        if archive_previous and path.exists():
            old = Playbook.load(str(path))
            self._archive(old)
        playbook.save(str(path))
        return str(path)

    def save_draft(self, playbook: Playbook) -> str:
        _validate_playbook_id(playbook.id)
        path = self.drafts_dir / f"{playbook.id}.yml"
        playbook.save(str(path))
        return str(path)

    def get(self, playbook_id: str) -> Optional[Playbook]:
        _validate_playbook_id(playbook_id)
        path = self.approved_dir / f"{playbook_id}.yml"
        if path.exists():
            return Playbook.load(str(path))
        return None

    def get_draft(self, playbook_id: str) -> Optional[Playbook]:
        _validate_playbook_id(playbook_id)
        path = self.drafts_dir / f"{playbook_id}.yml"
        if path.exists():
            return Playbook.load(str(path))
        return None

    def list_playbooks(self) -> list:
        return [
            Playbook.load(str(p))
            for p in sorted(self.approved_dir.glob("*.yml"))
            if p.name != "_registry.yml" and not p.name.endswith(".defaults.yml")
        ]

    def list_drafts(self) -> list:
        return [Playbook.load(str(p)) for p in sorted(self.drafts_dir.glob("*.yml"))]

    def match_ticket(self, ticket_type: str = "", text: str = "", source: str = "") -> list:
        matches = []
        for pb in self.list_playbooks():
            if pb.matches(ticket_type=ticket_type, text=text, source=source):
                matches.append(pb)
        return sorted(matches, key=lambda p: p.executions, reverse=True)

    def promote_draft(self, playbook_id: str) -> Optional[Playbook]:
        _validate_playbook_id(playbook_id)
        draft_path = self.drafts_dir / f"{playbook_id}.yml"
        if not draft_path.exists():
            return None
        pb = Playbook.load(str(draft_path))
        self.save(pb)
        draft_path.unlink()
        return pb

    def delete_draft(self, playbook_id: str) -> bool:
        _validate_playbook_id(playbook_id)
        path = self.drafts_dir / f"{playbook_id}.yml"
        if path.exists():
            path.unlink()
            return True
        return False

    def _archive(self, playbook: Playbook) -> None:
        archive_path = self.archive_dir / playbook.id
        archive_path.mkdir(parents=True, exist_ok=True)
        dest = archive_path / f"v{playbook.version}.yml"
        playbook.save(str(dest))

    def list_archive(self, playbook_id: str) -> list:
        _validate_playbook_id(playbook_id)
        archive_path = self.archive_dir / playbook_id
        if not archive_path.exists():
            return []
        return [Playbook.load(str(p)) for p in sorted(archive_path.glob("*.yml"))]
