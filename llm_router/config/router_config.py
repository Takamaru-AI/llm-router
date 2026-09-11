from __future__ import annotations

from dataclasses import dataclass

from .endpoint_config import EndpointConfig
from .model_config import DEFAULT_CONTEXT_LENGTH, ModelConfig
from .preset_config import PresetConfig
from .preset_model_config import PresetModelConfig
from .preset_route_config import PresetRouteConfig
from .server_config import ServerConfig


@dataclass(frozen=True)
class RouterConfig:
    server: ServerConfig
    endpoints: tuple[EndpointConfig, ...]
    global_system_prompt: str | None
    default_model: str
    presets: tuple[PresetConfig, ...]

    def find_endpoint(self, endpoint_id: str | None) -> EndpointConfig | None:
        return next(
            (endpoint for endpoint in self.endpoints if endpoint.id == endpoint_id),
            None,
        )

    def find_endpoint_for_model(
        self,
        model_id: str,
    ) -> tuple[EndpointConfig, ModelConfig] | None:
        for endpoint in self.endpoints:
            model = next(
                (
                    candidate
                    for candidate in endpoint.models
                    if candidate.id == model_id
                ),
                None,
            )
            if model is not None:
                return endpoint, model

        return None

    def endpoint_models(self) -> tuple[ModelConfig, ...]:
        return tuple(
            model
            for endpoint in self.endpoints
            for model in endpoint.models
        )

    def find_preset(self, preset_id: str) -> PresetConfig | None:
        return next(
            (preset for preset in self.presets if preset.id == preset_id),
            None,
        )

    @property
    def local_models(self) -> tuple[ModelConfig, ...]:
        local_endpoint = next(
            (e for e in self.endpoints if e.id is None),
            None,
        )

        return local_endpoint.models if local_endpoint else ()

    def remote_models(self) -> tuple[ModelConfig, ...]:
        return tuple(
            model
            for endpoint in self.endpoints
            if endpoint.id is not None
            for model in endpoint.models
        )

    def find_remote_model(self, model_id: str) -> ModelConfig | None:
        for endpoint in self.endpoints:
            if endpoint.id is not None:
                for model in endpoint.models:
                    if model.id == model_id:
                        return model

        return None

    def find_local_model(self, model_id: str) -> ModelConfig | None:
        for endpoint in self.endpoints:
            if endpoint.id is None:
                for model in endpoint.models:
                    if model.id == model_id:
                        return model

        return None

    def ordered_routes(self, preset: PresetConfig) -> tuple[PresetRouteConfig, ...]:
        return tuple(
            sorted(preset.routes, key=lambda route: route.priority, reverse=True)
        )

    def ordered_route_models(
        self,
        route: PresetRouteConfig,
    ) -> tuple[PresetModelConfig, ...]:
        return tuple(
            sorted(route.models, key=lambda model: model.priority, reverse=True)
        )

    def display_name_for(self, model_id: str) -> str:
        entry = self.find_endpoint_for_model(model_id)

        return entry[1].display_name if entry is not None else model_id

    def context_length_for(self, model_id: str | None) -> int:
        if model_id is None:
            return DEFAULT_CONTEXT_LENGTH

        entry = self.find_endpoint_for_model(model_id)

        return entry[1].context_length if entry is not None else DEFAULT_CONTEXT_LENGTH

    def system_prompt_for(self, requested_model: str) -> str | None:
        preset = self.find_preset(requested_model)
        if preset is not None and preset.system_prompt is not None:
            return preset.system_prompt

        return self.global_system_prompt

    def preset_context_length(self, preset: PresetConfig) -> int:
        return max(
            self.context_length_for(model.id)
            for route in preset.routes
            for model in route.models
        )