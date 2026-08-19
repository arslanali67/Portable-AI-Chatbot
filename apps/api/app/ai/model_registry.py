"""Model registry — (provider_id, model_id) → ModelMetadata.

No DB enums; ids are extensible strings.
"""


class DuplicateModelError(Exception):
    pass


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[tuple[str, str], object] = {}

    def register(self, model) -> None:
        key = (model.provider_id, model.model_id)
        if key in self._models:
            raise DuplicateModelError(f"model already registered: {model.model_id}")
        self._models[key] = model

    def get(self, provider_id: str, model_id: str) -> object:
        return self._models.get((provider_id, model_id))

    def list(self, provider_id: str) -> list[object]:
        return [m for (pid, _), m in self._models.items() if pid == provider_id]

    def exists(self, provider_id: str, model_id: str) -> bool:
        return (provider_id, model_id) in self._models
