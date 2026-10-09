"""Provider interfaces: the only place vendor SDKs may ever be imported.

Phase 1 defines the contracts and in-memory fakes; Phase 2 adds one real adapter per
capability. Business logic depends on these protocols, never on a vendor package.
"""

from aurevia.providers.model import (
    ModelMessage,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelUsage,
)
from aurevia.providers.speech import (
    AudioChunk,
    AudioFormat,
    STTConfig,
    STTProvider,
    TranscriptEvent,
    TTSConfig,
    TTSProvider,
)
from aurevia.providers.telephony import (
    AnsweredCall,
    DialError,
    DialFailure,
    OutboundCallRequest,
    TelephonyProvider,
)

__all__ = [
    "AnsweredCall",
    "AudioChunk",
    "AudioFormat",
    "DialError",
    "DialFailure",
    "ModelMessage",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "ModelStreamEvent",
    "ModelUsage",
    "OutboundCallRequest",
    "STTConfig",
    "STTProvider",
    "TTSConfig",
    "TTSProvider",
    "TelephonyProvider",
    "TranscriptEvent",
]
