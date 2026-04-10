"""
C 层 — 记忆层
负责身份对齐、三层记忆存储（Tier1/2/3）、Opportunity 构造与分发
"""

from .identity_store import IdentityStore
from .align_and_store import EventAligner

try:
    from .night_reflection import NightReflector
except ImportError:
    NightReflector = None
