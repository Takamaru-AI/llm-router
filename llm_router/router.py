from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .backend import BackendClient, BackendError
from .config import (
    EndpointConfig,
    PresetConfig,
    PresetModelConfig,
    PresetRouteConfig,
    RouterConfig,
)
from .state import State


class ModelRouter:
    def __init__(
        self,
        config: RouterConfig,
        backend_client: BackendClient,
        state: State,
    ) -> None:
        self._config = config
        self._backend_client = backend_client
        self._state = state

    async def route(
        self,
        body: dict[str, Any],
        requested_model: str,
    ) -> tuple[dict[str, Any] | AsyncIterator[bytes], str, bool] | None:
        system_prompt = self._config.system_prompt_for(requested_model)
        if system_prompt is not None:
            body["messages"] = _with_system_prompt(body["messages"], system_prompt)

        preset = self._config.find_preset(requested_model)
        if preset is not None:
            return await self._try_preset(body, preset)

        entry = self._config.find_endpoint_for_model(requested_model)
        if entry is not None:
            endpoint, model = entry
            result = await self._backend_client.request_endpoint(
                endpoint,
                model.id,
                body,
            )

            return self._success(result, model.id, is_switched=False)

        return None

    async def probe_local_model(self) -> str | None:
        local_endpoint = self._local_endpoint()
        if local_endpoint is None:
            return None

        return await self._backend_client.probe_local_model(local_endpoint)

    async def _try_preset(
        self,
        body: dict[str, Any],
        preset: PresetConfig,
    ) -> tuple[dict[str, Any] | AsyncIterator[bytes], str, bool] | None:
        is_fallback = False
        last_error: BackendError | None = None
        for route in self._config.ordered_routes(preset):
            try:
                successful_result = await self._try_preset_route(
                    body,
                    route,
                    is_fallback,
                )
            except BackendError as error:
                print(
                    f"[WARNING] {route.endpoint_id or 'local'} "
                    f"returned HTTP {error.status_code}, trying next route"
                )
                last_error = error
                is_fallback = True

                continue

            if successful_result is not None:
                return successful_result

            is_fallback = True

        if last_error is not None:
            raise last_error

        return None

    async def _try_preset_route(
        self,
        body: dict[str, Any],
        route: PresetRouteConfig,
        is_fallback: bool,
    ) -> tuple[dict[str, Any] | AsyncIterator[bytes], str, bool] | None:
        endpoint = self._config.find_endpoint(route.endpoint_id)
        if endpoint is None:
            return None

        if endpoint.id is None:
            return await self._try_preset_local_route(
                body,
                endpoint,
                route,
                is_fallback,
            )

        return await self._try_preset_remote_route(body, endpoint, route, is_fallback)

    async def _try_preset_local_route(
        self,
        body: dict[str, Any],
        endpoint: EndpointConfig,
        route: PresetRouteConfig,
        is_fallback: bool,
    ) -> tuple[dict[str, Any] | AsyncIterator[bytes], str, bool] | None:
        loaded_model = await self._backend_client.probe_local_model(endpoint)
        allowed_models = {model.id for model in route.models}
        if loaded_model not in allowed_models:
            return None

        result = await self._backend_client.request_endpoint(
            endpoint,
            loaded_model,
            body,
        )

        return self._success(result, loaded_model, is_switched=is_fallback)

    async def _try_preset_remote_route(
        self,
        body: dict[str, Any],
        endpoint: EndpointConfig,
        route: PresetRouteConfig,
        is_fallback: bool,
    ) -> tuple[dict[str, Any] | AsyncIterator[bytes], str, bool] | None:
        models = self._config.ordered_route_models(route)
        if not models:
            return None

        attempt_timeout = endpoint.attempt_timeout_seconds

        if attempt_timeout is not None and len(models) > 1:
            return await self._try_models_with_attempt_timeout(
                body,
                endpoint,
                models,
                is_fallback,
                attempt_timeout,
            )

        last_error: BackendError | None = None
        for index, preset_model in enumerate(models):
            try:
                result = await self._backend_client.request_endpoint(
                    endpoint,
                    preset_model.id,
                    body,
                )
            except BackendError as error:
                print(
                    f"[WARNING] {endpoint.id or 'local'} {preset_model.id} "
                    f"returned HTTP {error.status_code}, trying next model"
                )
                if index == len(models) - 1:
                    raise

                last_error = error

                continue

            successful_result = self._success(
                result,
                preset_model.id,
                is_switched=is_fallback or index > 0,
            )
            if successful_result is not None:
                return successful_result

        if last_error is not None:
            raise last_error

        return None

    async def _try_models_with_attempt_timeout(
        self,
        body: dict[str, Any],
        endpoint: EndpointConfig,
        models: tuple[PresetModelConfig, ...],
        is_fallback: bool,
        fast_fail_timeout: float,
    ) -> tuple[dict[str, Any] | AsyncIterator[bytes], str, bool] | None:
        for index, primary_model in enumerate(models):
            remaining_models = models[index + 1 :]
            if not remaining_models:
                result = await self._backend_client.request_endpoint(
                    endpoint,
                    primary_model.id,
                    body,
                )
                successful_result = self._success(
                    result,
                    primary_model.id,
                    is_switched=is_fallback or index > 0,
                )
                if successful_result is not None:
                    return successful_result

                continue

            try:
                result = await asyncio.wait_for(
                    self._backend_client.request_endpoint(
                        endpoint,
                        primary_model.id,
                        body,
                        read_timeout_override=fast_fail_timeout,
                    ),
                    timeout=fast_fail_timeout,
                )
            except asyncio.TimeoutError:
                continue
            except BackendError as error:
                print(
                    f"[WARNING] {endpoint.id or 'local'} {primary_model.id} "
                    f"returned HTTP {error.status_code}, trying next model"
                )

                continue
            except (httpx.HTTPError, OSError):
                continue

            if isinstance(result, AsyncIterator):
                return self._success(
                    result,
                    primary_model.id,
                    is_switched=is_fallback or index > 0,
                )

            successful_result = self._success(
                result,
                primary_model.id,
                is_switched=is_fallback or index > 0,
            )
            if successful_result is not None:
                return successful_result

        return None

    def _local_endpoint(self) -> EndpointConfig | None:
        return next(
            (endpoint for endpoint in self._config.endpoints if endpoint.id is None),
            None,
        )

    def _success(
        self,
        result: dict[str, Any] | AsyncIterator[bytes] | None,
        model: str,
        is_switched: bool,
    ) -> tuple[dict[str, Any] | AsyncIterator[bytes], str, bool] | None:
        if result is None:
            return None

        self._state.record(self._config.display_name_for(model))

        return result, model, is_switched


def _with_system_prompt(
    messages: list[Any],
    system_prompt: str,
) -> list[Any]:
    if (
        isinstance(messages[0], dict)
        and messages[0].get("role") == "system"
    ):
        return messages

    return [
        {"role": "system", "content": system_prompt},
        *messages,
    ]