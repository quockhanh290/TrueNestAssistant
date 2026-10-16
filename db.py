"""Legacy shim — db.py replaced by db/ package. Re-exports everything."""
from db import *  # noqa
from db import __all__ as _all
__all__ = _all
