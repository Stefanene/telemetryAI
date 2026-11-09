"""Independent operator capabilities; legacy modes are presets, explicit flags win."""
from dataclasses import asdict, dataclass
import os
from collections.abc import Mapping


@dataclass(frozen=True)
class Features:
    telemetry_enabled: bool = True
    knowledge_graph_enabled: bool = True
    verification_enabled: bool = True

    def __post_init__(self):
        if self.verification_enabled and not self.telemetry_enabled:
            raise ValueError("Verification requires telemetry")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None):
        env = os.environ if environ is None else environ
        mode = env.get('TELEMETRY_MODE', 'verified')
        presets = {'screenshot': (False, False, False), 'flat': (True, False, False),
                   'graph': (True, True, False), 'verified': (True, True, True)}
        if mode not in presets:
            raise ValueError('Unknown TELEMETRY_MODE')
        def flag(name, default):
            value = env.get(name)
            if value is None:
                return default
            if value.lower() not in {'0', '1', 'true', 'false'}:
                raise ValueError(f'{name} must be 0, 1, true, or false')
            return value.lower() in {'1', 'true'}
        t, k, v = presets[mode]
        t = flag('TELEMETRY_ENABLED', t)
        k = flag('KNOWLEDGE_GRAPH_ENABLED', k)
        # Verification performs file reads: it cannot silently re-enable disabled telemetry.
        v = flag('VERIFICATION_ENABLED', v and t)
        if v and not t:
            raise ValueError('VERIFICATION_ENABLED=1 requires TELEMETRY_ENABLED=1')
        return cls(t, k, v)

    def as_dict(self):
        return asdict(self)

    def environment(self):
        return {key.upper(): str(int(value)) for key, value in self.as_dict().items()}
