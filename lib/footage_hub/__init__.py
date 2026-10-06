"""FootageHub package init — re-exports only, no duplicate abstractions."""
from lib.footage_hub.contracts import NormalizedAsset, ProviderCapability  # noqa: F401
from lib.footage_hub.rights import RightsStatus, classify, validate  # noqa: F401
