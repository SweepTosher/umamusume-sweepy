import json
from datetime import datetime, timezone
from pathlib import Path

from career_bot.presets import slugify


def _coerce_race_ids(values):
    out = []
    for x in values or []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    return out


class RaceSchedulePresetStore:
    """Named race ID lists for the web race schedule (separate from character presets)."""

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.preset_dir = self.base_dir / "data" / "race_schedule_presets"

    def ensure(self):
        self.preset_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_slug(self, slug):
        return self.preset_dir / f"{slug}.json"

    def read_all(self):
        self.ensure()
        out = []
        for path in sorted(self.preset_dir.glob("*.json"), key=lambda p: p.stem.lower()):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            name = str(raw.get("name") or path.stem).strip() or path.stem
            races = raw.get("races")
            if not isinstance(races, list):
                races = []
            races = _coerce_race_ids(races)
            updated = raw.get("updated_at") or ""
            out.append({"name": name, "races": races, "updated_at": updated})
        return out

    def read_one(self, name):
        slug = slugify(name)
        path = self._path_for_slug(slug)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        races = raw.get("races")
        if not isinstance(races, list):
            races = []
        races = _coerce_race_ids(races)
        display = str(raw.get("name") or slug).strip() or slug
        return {"name": display, "races": races, "updated_at": raw.get("updated_at") or ""}

    def save(self, name, races):
        self.ensure()
        display = str(name or "").strip()
        if not display:
            raise ValueError("preset name required")
        slug = slugify(display)
        if not slug or slug == "preset":
            raise ValueError("invalid preset name")
        if not isinstance(races, list):
            races = []
        clean = _coerce_race_ids(races)
        payload = {
            "name": display,
            "races": clean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._path_for_slug(slug)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def delete(self, name):
        slug = slugify(name)
        path = self._path_for_slug(slug)
        if path.exists():
            path.unlink()
            return True
        return False
