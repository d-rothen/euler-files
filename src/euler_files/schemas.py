"""Schema helpers for CLI and --input-json payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar

import click

JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"

_INPUT_JSON_SCHEMAS: Dict[str, Dict[str, Any]] = {}

F = TypeVar("F")


def register_input_json_schema(command_path: str, schema: Dict[str, Any]) -> Callable[[F], F]:
    """Register a JSON schema for a command's --input-json payload."""
    registered = deepcopy(schema)
    registered.setdefault("$schema", JSON_SCHEMA_DRAFT)
    registered.setdefault("title", f"{command_path} --input-json payload")

    def decorator(obj: F) -> F:
        _INPUT_JSON_SCHEMAS[command_path] = deepcopy(registered)
        return obj

    return decorator


def get_input_json_schema(command_path: str) -> Dict[str, Any]:
    """Return the registered input schema for a command path."""
    schema = _INPUT_JSON_SCHEMAS.get(command_path)
    if schema is None:
        raise ValueError(f"No --input-json schema registered for '{command_path}'.")
    return deepcopy(schema)


def get_all_input_json_schemas() -> Dict[str, Dict[str, Any]]:
    """Return every registered input schema keyed by command path."""
    return deepcopy(_INPUT_JSON_SCHEMAS)


def build_schema_payload(
    root_command: click.BaseCommand,
    command_path: Optional[str] = None,
    kind: str = "all",
) -> Dict[str, Any]:
    """Build the schema payload exposed by the schema CLI command."""
    payload: Dict[str, Any] = {
        "command": "schema",
        "kind": kind,
    }

    if command_path:
        payload["target_command"] = command_path

    if kind in ("all", "cli"):
        payload["cli"] = get_click_command_schema(root_command, command_path)

    if kind in ("all", "input"):
        if command_path:
            payload["input_json"] = get_input_json_schema(command_path)
        else:
            payload["input_json"] = get_all_input_json_schemas()

    return payload


def get_click_command_schema(
    root_command: click.BaseCommand,
    command_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Return Click's own invocation schema for a command path."""
    root_info_name = "euler-files" if root_command.name == "main" else (root_command.name or "command")
    ctx = click.Context(root_command, info_name=root_info_name)

    if not command_path:
        with ctx.scope(cleanup=False):
            info = root_command.to_info_dict(ctx)
        info["name"] = root_info_name
        return info

    command, sub_ctx = _resolve_click_command(root_command, ctx, command_path)
    with sub_ctx.scope(cleanup=False):
        return command.to_info_dict(sub_ctx)


def _resolve_click_command(
    root_command: click.BaseCommand,
    root_ctx: click.Context,
    command_path: str,
) -> Tuple[click.BaseCommand, click.Context]:
    """Resolve a dotted command path like 'apptainer.build'."""
    command = root_command
    ctx = root_ctx

    for segment in _split_command_path(command_path):
        if not isinstance(command, click.Group):
            raise ValueError(f"'{command_path}' is not a valid command path.")
        next_command = command.get_command(ctx, segment)
        if next_command is None:
            raise ValueError(f"Unknown command path '{command_path}'.")
        ctx = ctx._make_sub_context(next_command)
        command = next_command

    return command, ctx


def _split_command_path(command_path: str) -> List[str]:
    """Split dotted or space-separated command paths into segments."""
    dotted = command_path.replace(" ", ".")
    return [segment for segment in dotted.split(".") if segment]


def string_schema(description: str, enum: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Build a string-typed JSON schema property."""
    schema: Dict[str, Any] = {
        "type": "string",
        "description": description,
    }
    if enum is not None:
        schema["enum"] = list(enum)
    return schema


def boolean_schema(description: str) -> Dict[str, Any]:
    """Build a boolean-typed JSON schema property."""
    return {
        "type": "boolean",
        "description": description,
    }


def integer_schema(description: str) -> Dict[str, Any]:
    """Build an integer-typed JSON schema property."""
    return {
        "type": "integer",
        "description": description,
    }


def number_schema(description: str) -> Dict[str, Any]:
    """Build a number-typed JSON schema property."""
    return {
        "type": "number",
        "description": description,
    }


def string_array_schema(description: str) -> Dict[str, Any]:
    """Build an array-of-strings schema property."""
    return {
        "type": "array",
        "description": description,
        "items": {"type": "string"},
    }


def object_schema(
    properties: Dict[str, Any],
    required: Iterable[str] = (),
    description: Optional[str] = None,
    additional_properties: Any = False,
) -> Dict[str, Any]:
    """Build an object schema with common defaults."""
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    required_list = list(required)
    if required_list:
        schema["required"] = required_list
    if description:
        schema["description"] = description
    return schema


def alias_string_schema(description: str, alias_for: str) -> Dict[str, Any]:
    """Build a string property documenting an accepted alias."""
    return string_schema(f"{description} Accepted as an alias for '{alias_for}'.")


def alias_string_array_schema(description: str, alias_for: str) -> Dict[str, Any]:
    """Build an array-of-strings property documenting an accepted alias."""
    return string_array_schema(f"{description} Accepted as an alias for '{alias_for}'.")


def euler_config_schema_ref() -> Dict[str, Any]:
    """Reference the top-level config definition."""
    return {"$ref": "#/$defs/EulerFilesConfig"}


def apptainer_config_schema_ref() -> Dict[str, Any]:
    """Reference the apptainer config definition."""
    return {"$ref": "#/$defs/ApptainerConfig"}


def config_schema_defs() -> Dict[str, Any]:
    """Shared JSON Schema definitions for config payloads."""
    return {
        "VarConfig": object_schema(
            {
                "source": string_schema("Absolute path to the persistent source directory."),
                "enabled": boolean_schema("Whether the managed variable is enabled."),
            },
            required=("source",),
            description="Configuration for one managed environment variable.",
        ),
        "ApptainerImageConfig": object_schema(
            {
                "venv_name": string_schema("Name of the source venv under venv_base."),
                "python_version": string_schema("Full Python version string, for example '3.11.5'."),
                "sif_filename": string_schema("Filename of the built .sif image."),
                "built_at": number_schema("Unix timestamp of the most recent build."),
                "enabled": boolean_schema("Whether the image is enabled for sync."),
            },
            required=("venv_name", "python_version", "sif_filename"),
            description="Stored metadata for one Apptainer image.",
        ),
        "ApptainerConfig": object_schema(
            {
                "venv_base": string_schema("Directory containing the managed Python environments."),
                "sif_store": string_schema("Persistent storage directory for built .sif files."),
                "scratch_sif_dir": string_schema("Scratch destination for synced .sif files."),
                "base_image": string_schema("Apptainer base image template."),
                "container_venv_path": string_schema("Canonical venv path inside the container."),
                "build_args": string_array_schema("Extra arguments passed to 'apptainer build'."),
                "images": {
                    "type": "object",
                    "description": "Known image metadata keyed by environment name.",
                    "additionalProperties": {"$ref": "#/$defs/ApptainerImageConfig"},
                },
            },
            required=("venv_base", "sif_store", "scratch_sif_dir"),
            description="Apptainer-related configuration.",
        ),
        "MigrationRecord": object_schema(
            {
                "old_path": string_schema("Original absolute path."),
                "new_path": string_schema("Destination absolute path."),
                "migrated_at": number_schema("Unix timestamp when the migration was recorded."),
                "field_name": string_schema("Config field that changed."),
                "var_name": string_schema("Environment variable name for variable migrations."),
            },
            required=("old_path", "new_path", "migrated_at", "field_name"),
            description="Recorded migration entry.",
        ),
        "EulerFilesConfig": object_schema(
            {
                "version": integer_schema("Config file version."),
                "scratch_base": string_schema("Base scratch directory used for cache sync targets."),
                "cache_root": string_schema("Relative path under scratch_base where euler-files stores caches."),
                "vars": {
                    "type": "object",
                    "description": "Managed variables keyed by environment variable name.",
                    "additionalProperties": {"$ref": "#/$defs/VarConfig"},
                },
                "rsync_extra_args": string_array_schema("Extra arguments passed to rsync."),
                "parallel_jobs": integer_schema("Number of concurrent sync jobs."),
                "lock_timeout_seconds": integer_schema("Per-variable flock timeout in seconds."),
                "skip_if_fresh_seconds": integer_schema("Marker freshness threshold in seconds."),
                "apptainer": {"$ref": "#/$defs/ApptainerConfig"},
                "migrations": {
                    "type": "array",
                    "description": "Migration history entries.",
                    "items": {"$ref": "#/$defs/MigrationRecord"},
                },
            },
            required=("scratch_base", "vars"),
            description="Top-level euler-files configuration document.",
        ),
    }


def init_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files init --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files init --input-json payload",
        "description": "Either a raw euler-files config object or an object wrapping it under 'config'.",
        "$defs": config_schema_defs(),
        "oneOf": [
            euler_config_schema_ref(),
            object_schema(
                {
                    "config": euler_config_schema_ref(),
                },
                required=("config",),
                description="Wrapper object containing the full config under 'config'.",
            ),
        ],
    }


def apptainer_init_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files apptainer init --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files apptainer init --input-json payload",
        "description": "Either a raw apptainer config object or an object wrapping it under 'apptainer'.",
        "$defs": config_schema_defs(),
        "oneOf": [
            apptainer_config_schema_ref(),
            object_schema(
                {
                    "apptainer": apptainer_config_schema_ref(),
                },
                required=("apptainer",),
                description="Wrapper object containing the apptainer config under 'apptainer'.",
            ),
        ],
    }


def sync_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files sync --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files sync --input-json payload",
        "description": "Optional arguments for the sync command.",
        **object_schema(
            {
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
                "force": boolean_schema("Equivalent to '--force'."),
                "verbose": boolean_schema("Equivalent to '--verbose'."),
                "vars": string_array_schema("Equivalent to repeating '--var'."),
                "only_vars": alias_string_array_schema(
                    "Alternative field name for the variable list.",
                    "vars",
                ),
            }
        ),
    }


def push_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files push --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files push --input-json payload",
        "description": "Optional arguments for the push command.",
        **object_schema(
            {
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
                "vars": string_array_schema("Equivalent to repeating '--var'."),
                "only_vars": alias_string_array_schema(
                    "Alternative field name for the variable list.",
                    "vars",
                ),
            }
        ),
    }


def apptainer_build_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files apptainer build --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files apptainer build --input-json payload",
        "description": "Optional arguments for building an Apptainer image.",
        **object_schema(
            {
                "venv_name": string_schema("Name of the venv to build."),
                "force": boolean_schema("Equivalent to '--force'."),
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
            }
        ),
    }


def apptainer_prune_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files apptainer prune --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files apptainer prune --input-json payload",
        "description": "Optional arguments for pruning venvs and/or images.",
        **object_schema(
            {
                "image_name": string_schema("Name of the environment/image to prune."),
                "venv_name": alias_string_schema(
                    "Accepted alias for the image/environment name.",
                    "image_name",
                ),
                "mode": string_schema(
                    "What to remove.",
                    enum=("both", "venv", "sif"),
                ),
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
                "yes": boolean_schema("Equivalent to '--yes'."),
            }
        ),
    }


def apptainer_fixup_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files apptainer fixup --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files apptainer fixup --input-json payload",
        "description": "Optional arguments for fixing venv internal paths.",
        **object_schema(
            {
                "venv_name": string_schema("Fix only this venv; omit to process all venvs."),
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
            }
        ),
    }


def apptainer_sync_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files apptainer sync --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files apptainer sync --input-json payload",
        "description": "Optional arguments for syncing .sif images to scratch.",
        **object_schema(
            {
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
                "force": boolean_schema("Equivalent to '--force'."),
                "images": string_array_schema("Equivalent to repeating '--image'."),
                "only_images": alias_string_array_schema(
                    "Alternative field name for the image list.",
                    "images",
                ),
            }
        ),
    }


def venv_install_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files venv install --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files venv install --input-json payload",
        "description": "Arguments for creating/reusing a uv environment and installing packages.",
        **object_schema(
            {
                "env_name": string_schema("Target environment name under the configured venv base."),
                "packages": string_array_schema("Package requirement strings to install."),
                "requirements": alias_string_array_schema(
                    "Accepted alias for the package requirement list.",
                    "packages",
                ),
                "python": string_schema("Python version or interpreter passed to 'uv venv'."),
                "venv_base": string_schema("Override for the configured venv base directory."),
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
            },
            required=("env_name",),
        ),
        "anyOf": [
            {"required": ["packages"]},
            {"required": ["requirements"]},
        ],
    }


def migrate_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files migrate --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files migrate --input-json payload",
        "description": "Arguments for migrating a managed path to a new location.",
        **object_schema(
            {
                "what": string_schema("Managed variable or config field to migrate."),
                "to": string_schema("Destination path."),
                "to_path": alias_string_schema("Accepted alias for the destination path.", "to"),
                "new_path": alias_string_schema("Accepted alias for the destination path.", "to"),
                "dry_run": boolean_schema("Equivalent to '--dry-run'."),
                "keep_old": boolean_schema("Keep the old directory after migration."),
                "no_delete": boolean_schema("Accepted alias for 'keep_old'."),
                "yes": boolean_schema("Equivalent to '--yes'."),
            }
        ),
    }


def shell_init_input_schema() -> Dict[str, Any]:
    """Schema for `euler-files shell-init --input-json`."""
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "title": "euler-files shell-init --input-json payload",
        "description": "Arguments for generating shell integration code.",
        **object_schema(
            {
                "shell": string_schema(
                    "Target shell language for the generated helper.",
                    enum=("bash", "zsh", "fish"),
                ),
            }
        ),
    }
