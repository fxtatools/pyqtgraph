
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.util import find_spec

    if find_spec("qtpy") is not None:
        from qtpy.QtWidgets import *  # noqa: F403 F401
