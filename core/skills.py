"""Discoverable, permission-aware skill catalog built on FRIDAY's tool registry."""
from __future__ import annotations

import json
from pathlib import Path


class SkillManager:
    def __init__(self, registry, state_file=None):
        self.registry = registry
        self.state_file = Path(state_file or 'memory/skills.json')
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = self._load()

    def _load(self):
        try:
            return set(json.loads(self.state_file.read_text()))
        except (OSError, ValueError):
            return set(self.registry.tools)

    def _save(self):
        self.state_file.write_text(json.dumps(sorted(self.enabled), indent=2))

    def catalog(self):
        return [
            {
                'name': name,
                'description': data['declaration'].get('description', ''),
                'enabled': name in self.enabled,
            }
            for name, data in self.registry.tools.items()
        ]

    def enable(self, name):
        if name not in self.registry.tools:
            raise KeyError(name)
        self.enabled.add(name)
        self._save()
        return f"Enabled skill: {name}"

    def disable(self, name):
        if name not in self.registry.tools:
            raise KeyError(name)
        self.enabled.discard(name)
        self._save()
        return f"Disabled skill: {name}"

    def declarations(self):
        return [d['declaration'] for n, d in self.registry.tools.items() if n in self.enabled]
