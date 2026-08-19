"""AI capabilities."""

import enum


class AICapability(str, enum.Enum):
    TEXT_GENERATION = "text_generation"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"
    EMBEDDINGS = "embeddings"
    IMAGE_GENERATION = "image_generation"
    JSON_MODE = "json_mode"
    REASONING = "reasoning"
