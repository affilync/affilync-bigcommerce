"""Portable column types shared by the models.

Production runs postgres and keeps real JSONB. The test lane runs sqlite,
whose compiler has no visit_JSONB — create_all crashed before a single test
table existed. with_variant leaves the postgres DDL byte-identical and gives
sqlite the generic JSON type.
"""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB as _PGJSONB

JSONB = _PGJSONB().with_variant(JSON(), "sqlite")
