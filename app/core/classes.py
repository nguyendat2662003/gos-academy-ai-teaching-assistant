"""Load and validate the class registry (config/classes.yaml)."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from app.core.config import get_settings


class GroupConfig(BaseModel):
    channel: str
    external_group_id: str


class ClassConfig(BaseModel):
    id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]*$")
    name: str
    enabled: bool = True
    instructor_name: str
    instructor_contact: str
    section_prefixes: list[str] = []
    aliases: list[str] = []
    groups: list[GroupConfig] = []


class SharedScopeConfig(BaseModel):
    id: str = "COMMON"
    name: str
    section_prefixes: list[str] = []


class ClassRegistry(BaseModel):
    shared_scope: SharedScopeConfig
    classes: list[ClassConfig]

    @model_validator(mode="after")
    def _check_unique(self) -> "ClassRegistry":
        ids = [c.id for c in self.classes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate class id")
        if self.shared_scope.id in ids:
            raise ValueError("shared scope id must not be a class id")
        groups = [(g.channel, g.external_group_id) for c in self.classes for g in c.groups]
        if len(groups) != len(set(groups)):
            raise ValueError("a (channel, group) is mapped to more than one class")
        prefixes = self.shared_scope.section_prefixes + [p for c in self.classes for p in c.section_prefixes]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("a section prefix is mapped to more than one scope")
        return self

    @property
    def scope_ids(self) -> set[str]:
        """Every id a document can be attached to: the classes plus the shared scope."""
        return {c.id for c in self.classes} | {self.shared_scope.id}

    def scope_for_prefix(self, prefix: str | None) -> str | None:
        """'GS' -> 'GS-KPI-01', 'COMMON' -> 'COMMON', unknown/None -> None."""
        if prefix is None:
            return None
        if prefix in self.shared_scope.section_prefixes:
            return self.shared_scope.id
        return next((c.id for c in self.classes if prefix in c.section_prefixes), None)


def load_registry(path: str | Path) -> ClassRegistry:
    """Parse and validate a classes.yaml file."""
    with open(path, encoding="utf-8") as fh:
        return ClassRegistry.model_validate(yaml.safe_load(fh))


@lru_cache
def get_registry() -> ClassRegistry:
    """Return the registry configured by CLASSES_CONFIG_PATH."""
    return load_registry(get_settings().classes_config_path)
