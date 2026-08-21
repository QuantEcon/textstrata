"""People roster: resolves commit identities to a role.

Resolution is by e-mail and handle only — never by display name, because
several contributors commit under two names on one address. The accepted
file shape is a list under `people:` (or `reviewers:`) with `id`/`handle`,
`role`, `emails` and optional `names`; QuantEcon's `team/reviewers.yml` is
read as-is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Person:
    id: str
    role: str
    emails: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)


@dataclass
class Roster:
    people: list[Person] = field(default_factory=list)
    by_email: dict[str, Person] = field(default_factory=dict)
    by_handle: dict[str, Person] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> Roster:
        r = cls()
        if path is None:
            return r
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        entries = raw.get("people") or raw.get("reviewers") or []
        for e in entries:
            pid = e.get("id") or e.get("handle")
            if not pid or not e.get("role"):
                continue
            p = Person(id=str(pid), role=str(e["role"]),
                       emails=[str(x).lower() for x in (e.get("emails") or [])],
                       names=[str(x) for x in (e.get("names") or ([e["name"]] if e.get("name") else []))])
            r.people.append(p)
            r.by_handle[p.id.lower()] = p
            for em in p.emails:
                r.by_email[em] = p
        return r

    def resolve_email(self, email: str) -> Person | None:
        email = (email or "").lower()
        if email in self.by_email:
            return self.by_email[email]
        # GitHub noreply addresses carry the handle: 12345+handle@users.noreply.github.com
        if email.endswith("@users.noreply.github.com"):
            local = email.split("@", 1)[0]
            handle = local.split("+", 1)[1] if "+" in local else local
            return self.by_handle.get(handle.lower())
        return None

    def resolve_trailer(self, value: str) -> Person | None:
        """`Co-authored-by: Name <email>` -> Person via the e-mail, else via a bare handle."""
        v = value.strip()
        if "<" in v and v.endswith(">"):
            return self.resolve_email(v[v.rindex("<") + 1:-1])
        return self.by_handle.get(v.lstrip("@").lower())
