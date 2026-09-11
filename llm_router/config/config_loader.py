from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .authentication_config import AuthenticationConfig
from .config_error import ConfigError
from .endpoint_config import EndpointConfig
from .model_config import ModelConfig
from .preset_config import PresetConfig
from .preset_model_config import PresetModelConfig
from .preset_route_config import PresetRouteConfig
from .router_config import RouterConfig
from .server_config import ServerConfig


class ConfigLoader:
    def load(self, path: Path) -> RouterConfig:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exception:
            raise ConfigError(
                f"Cannot read configuration file {path}: {exception}"
            ) from exception

        try:
            document = yaml.safe_load(content)
        except yaml.YAMLError as exception:
            raise ConfigError(f"Invalid YAML in {path}: {exception}") from exception

        if not isinstance(document, dict):
            raise ConfigError("Configuration root must be a mapping")

        return self._parse(document)

    def _parse(self, document: dict[str, Any]) -> RouterConfig:
        server = self._mapping(document, "server")
        presets = self._presets(self._sequence(document, "presets"))
        router = self._mapping(document, "router")
        default_model = self._string(router, "default_model")
        global_system_prompt = self._system_prompt(router, "system_prompt")

        endpoints = list(self._remote_endpoints(document))

        local_backend_data = document.get("local_backend")
        if local_backend_data is not None:
            local_endpoint = self._local_endpoint(
                self._mapping(document, "local_backend")
            )
            endpoints.insert(0, local_endpoint)

        endpoints_tuple = tuple(endpoints)
        self._validate_presets(presets, endpoints_tuple)
        if default_model not in {preset.id for preset in presets}:
            raise ConfigError("router.default_model must name a configured preset")

        return RouterConfig(
            server=ServerConfig(
                host=self._string(server, "host"),
                port=self._integer(server, "port"),
            ),
            endpoints=endpoints_tuple,
            global_system_prompt=global_system_prompt,
            default_model=default_model,
            presets=presets,
        )

    def _local_endpoint(self, data: dict[str, Any]) -> EndpointConfig:
        return EndpointConfig(
            id=None,
            openai_base_url=self._openai_base_url(data),
            authentication=AuthenticationConfig(),
            connect_timeout_seconds=self._number(data, "connect_timeout_seconds"),
            read_timeout_seconds=self._number(data, "read_timeout_seconds"),
            health_check_timeout_seconds=self._number(
                data, "health_check_timeout_seconds"
            ),
            models=(),
        )

    def _remote_endpoints(self, document: dict[str, Any]) -> tuple[EndpointConfig, ...]:
        data = document.get("remote_endpoints")
        if data is None:
            return ()

        return tuple(
            self._endpoint(self._item_mapping(item))
            for item in self._sequence(document, "remote_endpoints")
        )

    def _endpoint(self, data: dict[str, Any]) -> EndpointConfig:
        authentication_data = data.get("authentication")
        authentication = (
            self._authentication(self._mapping(data, "authentication"))
            if authentication_data is not None
            else AuthenticationConfig()
        )

        return EndpointConfig(
            id=self._string(data, "id"),
            openai_base_url=self._openai_base_url(data),
            authentication=authentication,
            connect_timeout_seconds=self._number(data, "connect_timeout_seconds"),
            read_timeout_seconds=self._number(data, "read_timeout_seconds"),
            attempt_timeout_seconds=self._optional_number(
                data, "attempt_timeout_seconds"
            ),
            health_check_timeout_seconds=self._optional_number(
                data, "health_check_timeout_seconds"
            )
            or 3.0,
            models=self._models(self._sequence(data, "models")),
        )

    def _authentication(self, data: dict[str, Any]) -> AuthenticationConfig:
        authentication_type = self._string(data, "type").lower()
        if authentication_type not in {"none", "bearer", "header"}:
            raise ConfigError("authentication.type must be none, bearer, or header")

        environment_variable = self._optional_string(data, "environment_variable")
        header_name = self._optional_string(data, "header_name")
        if authentication_type == "none":
            return AuthenticationConfig()

        if environment_variable is None:
            raise ConfigError("Authenticated endpoints need an environment_variable")

        if authentication_type == "header" and header_name is None:
            raise ConfigError("Header authentication needs a header_name")

        return AuthenticationConfig(
            type=authentication_type,
            environment_variable=environment_variable,
            header_name=header_name,
        )

    def _openai_base_url(self, data: dict[str, Any]) -> str:
        url = self._string(data, "openai_base_url").rstrip("/")
        if not url.endswith("/v1"):
            raise ConfigError("openai_base_url must end with /v1")

        return url

    def _validate_presets(
        self,
        presets: tuple[PresetConfig, ...],
        endpoints: tuple[EndpointConfig, ...],
    ) -> None:
        endpoint_models_by_id = {
            endpoint.id: {model.id for model in endpoint.models}
            for endpoint in endpoints
        }
        for preset in presets:
            for route in preset.routes:
                if route.endpoint_id is None:
                    if not any(
                        route.models
                        for endpoint in endpoints
                        if endpoint.id is None
                    ):
                        raise ConfigError(
                            f"Preset route in {preset.id} references an "
                            "unknown endpoint"
                        )

                    continue

                if route.endpoint_id not in endpoint_models_by_id:
                    raise ConfigError(
                        f"Preset route in {preset.id} references unknown endpoint "
                        f"{route.endpoint_id}"
                    )

                endpoint_model_ids = endpoint_models_by_id[route.endpoint_id]
                unknown = {
                    model.id
                    for model in route.models
                    if model.id not in endpoint_model_ids
                }
                if unknown:
                    raise ConfigError(
                        f"Preset route in {preset.id} references unknown model(s): "
                        f"{', '.join(sorted(unknown))}"
                    )

    def _presets(self, items: list[Any]) -> tuple[PresetConfig, ...]:
        presets = tuple(self._preset(self._item_mapping(item)) for item in items)
        if not presets:
            raise ConfigError("presets cannot be empty")

        if len({preset.id for preset in presets}) != len(presets):
            raise ConfigError("Each preset id must be unique")

        return presets

    def _preset(self, data: dict[str, Any]) -> PresetConfig:
        return PresetConfig(
            id=self._string(data, "id").lower(),
            display_name=self._string(data, "display_name"),
            system_prompt=self._system_prompt(data, "system_prompt"),
            routes=tuple(
                self._preset_route(self._item_mapping(item))
                for item in self._sequence(data, "routes")
            ),
        )

    def _preset_route(self, data: dict[str, Any]) -> PresetRouteConfig:
        models = tuple(
            PresetModelConfig(
                id=self._string(self._item_mapping(item), "id"),
                priority=self._integer(self._item_mapping(item), "priority"),
            )
            for item in self._sequence(data, "models")
        )
        if not models:
            raise ConfigError("Preset routes need at least one model")

        return PresetRouteConfig(
            endpoint_id=self._optional_string(data, "endpoint_id"),
            priority=self._integer(data, "priority"),
            models=models,
        )

    def _models(self, items: list[Any]) -> tuple[ModelConfig, ...]:
        models = tuple(
            ModelConfig(
                id=self._string(self._item_mapping(item), "id"),
                display_name=self._string(self._item_mapping(item), "display_name"),
                context_length=self._integer(
                    self._item_mapping(item),
                    "context_length",
                ),
            )
            for item in items
        )
        if not models:
            raise ConfigError("Model inventories cannot be empty")

        return models

    def _mapping(self, data: dict[str, Any], key: str) -> dict[str, Any]:
        value = data.get(key)
        if not isinstance(value, dict):
            raise ConfigError(f"{key} must be a mapping")

        return value

    def _sequence(self, data: dict[str, Any], key: str) -> list[Any]:
        value = data.get(key)
        if not isinstance(value, list):
            raise ConfigError(f"{key} must be a list")

        return value

    def _item_mapping(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ConfigError("Each entry must be a mapping")

        return value

    def _string(self, data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{key} must be a non-empty string")

        return value.strip()

    def _optional_string(self, data: dict[str, Any], key: str) -> str | None:
        value = data.get(key)
        if value is None:
            return None

        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{key} must be a non-empty string when provided")

        return value.strip()

    def _system_prompt(self, data: dict[str, Any], key: str) -> str | None:
        value = data.get(key, "")
        if value is None:
            return None

        if not isinstance(value, str):
            raise ConfigError(f"{key} must be a string")

        return value.strip() or None

    def _integer(self, data: dict[str, Any], key: str) -> int:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"{key} must be a positive integer")

        return value

    def _number(self, data: dict[str, Any], key: str) -> float:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"{key} must be a positive number")

        return float(value)

    def _optional_number(self, data: dict[str, Any], key: str) -> float | None:
        value = data.get(key)
        if value is None:
            return None

        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"{key} must be a positive number when provided")

        return float(value)