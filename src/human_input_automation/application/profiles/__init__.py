"""Profile persistence: versioned JSON storage and target re-resolution.

Persistence lives here, in the application layer. The core knows nothing about
files, schemas or directories, and nothing in this package imports Qt or a
platform library.
"""

from .repository import (
    ProfileRepository,
    default_data_directory,
    default_profile_directory,
)
from .resolver import MATCH_PRIORITY, ResolutionResult, TargetResolver
from .schema import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    Profile,
    ProfileError,
    ProfileFormatError,
    ProfileNotFoundError,
    ProfileState,
    ProfileStorageError,
    ProfileSummary,
    TargetIdentity,
    UnsupportedSchemaError,
    new_profile_id,
)
from .serialization import (
    MIGRATIONS,
    action_from_dict,
    action_to_dict,
    migrate,
    plan_from_dict,
    plan_to_dict,
    profile_from_dict,
    profile_to_dict,
)
from .service import LoadedProfile, ProfileService

__all__ = [
    "MATCH_PRIORITY",
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "LoadedProfile",
    "Profile",
    "ProfileError",
    "ProfileFormatError",
    "ProfileNotFoundError",
    "ProfileRepository",
    "ProfileService",
    "ProfileState",
    "ProfileStorageError",
    "ProfileSummary",
    "ResolutionResult",
    "TargetIdentity",
    "TargetResolver",
    "UnsupportedSchemaError",
    "action_from_dict",
    "action_to_dict",
    "default_data_directory",
    "default_profile_directory",
    "migrate",
    "new_profile_id",
    "plan_from_dict",
    "plan_to_dict",
    "profile_from_dict",
    "profile_to_dict",
]
