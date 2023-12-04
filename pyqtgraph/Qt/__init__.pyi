"""
This stub file is to aid in the PyCharm auto-completion of the Qt imports.
"""

from typing import Union

from . import QtCore, QtWidgets

App: QtWidgets.QApplication
VERSION_INFO: str
QT_LIB: str
QtVersion: str
PYSIDE: str
PYSIDE2: str
PYSIDE6: str
PYQT4: str
PYQT5: str
PYQT6: str
def exec_() -> QtWidgets.QApplication: ...
def mkQApp(name: Union[str, None] = None) -> QtWidgets.QApplication: ...
def isQObjectAlive(obj: QtCore.QObject) -> bool: ...
