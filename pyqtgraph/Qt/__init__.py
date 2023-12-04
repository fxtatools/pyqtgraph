"""
This module exists to smooth out some of the differences between Qt versions.

* Automatically import Qt lib depending on availability
* Allow you to import QtCore/QtGui from pyqtgraph.Qt without specifying which Qt wrapper
  you want to use.
"""
import os
import re
import subprocess
import sys
import time
import traceback
import warnings

from importlib.util import find_spec
from types import ModuleType
import typing as t

PYSIDE = 'PySide'
PYSIDE2 = 'PySide2'
PYSIDE6 = 'PySide6'
PYQT4 = 'PyQt4'
PYQT5 = 'PyQt5'
PYQT6 = 'PyQt6'

QT_LIB = os.getenv('PYQTGRAPH_QT_LIB')
QTPY_QT_API = os.getenv('QT_API')
if QT_LIB is None:
    QT_LIB = QTPY_QT_API

if QT_LIB is not None:
    # normalize the module name case, using the namespace
    # of this module to determine the package name for import
    _qt_lib = sys.modules[__name__].__dict__.get(QT_LIB.upper())
    if _qt_lib is None:
        raise RuntimeError("QT_LIB not recognized", QT_LIB)
    QT_LIB = _qt_lib
    try:
        __import__(QT_LIB)
    except ModuleNotFoundError:
        raise ModuleNotFoundError(f"Environment variable PYQTGRAPH_QT_LIB is set to '{os.getenv('PYQTGRAPH_QT_LIB')}', but no module with this name was found.")

## Automatically determine which Qt package to use (unless specified by
## environment variable).
## This is done by first checking to see whether one of the libraries
## is already imported. If not, then attempt to import in the order
## specified in libOrder.
if QT_LIB is None:
    libOrder = [PYQT6, PYSIDE6, PYQT5, PYSIDE2]

    for lib in libOrder:
        if lib in sys.modules:
            QT_LIB = lib
            break

if QT_LIB is None:
    for lib in libOrder:
        qt = lib + '.QtCore'
        try:
            __import__(qt)
            QT_LIB = lib
            break
        except ImportError:
            pass

if QT_LIB is None:
    raise Exception("PyQtGraph requires one of PyQt5, PyQt6, PySide2 or PySide6; none of these packages could be imported.")


if find_spec("qtpy"):
    if QTPY_QT_API is None:
        # set the preferred library for import with qtpy
        os.environ["QT_API"] = QT_LIB
        QTPY_QT_API = QT_LIB
    elif QTPY_QT_API is not None and QT_LIB.lower() != QTPY_QT_API.lower():
        # warn on mismatch, before qtpy import
        raise warnings.warn("QT_LIB %r does not match os.environ QT_API %r" % (QT_LIB, QTPY_QT_API,),
                            stacklevel=2)

    if "FORCE_QT_API" not in os.environ:
        # ensure the selected package will be used by qtpy
        os.environ["FORCE_QT_API"] = "1"

    try:
        import qtpy
    except Exception:
        traceback.print_exception(*sys.exc_info())
        warnings.warn("Unable to import qtpy", stacklevel=2)
    else:
        # check parity after qtpy import, warn on mistmatch
        if QT_LIB.lower() != qtpy.API_NAME.lower():
            warnings.warn("QT_LIB %r does not match qtpy.API_NAME %r" % (QT_LIB, qtpy.API_NAME,),
                        stacklevel=2)


class FailedImport(object):
    """Used to defer ImportErrors until we are sure the module is needed.
    """
    def __init__(self, err):
        self.err = err
        
    def __getattr__(self, attr):
        raise self.err


# Make a loadUiType function like PyQt has

# Credit:
# http://stackoverflow.com/questions/4442286/python-code-genration-with-pyside-uic/14195313#14195313

class _StringIO(object):
    """Alternative to built-in StringIO needed to circumvent unicode/ascii issues"""
    def __init__(self):
        self.data = []
    
    def write(self, data):
        self.data.append(data)
        
    def getvalue(self):
        return ''.join(map(str, self.data)).encode('utf8')

    
def _loadUiType(uiFile):
    """
    PySide lacks a "loadUiType" command like PyQt4's, so we have to convert
    the ui file to py code in-memory first and then execute it in a
    special frame to retrieve the form_class.

    from stackoverflow: http://stackoverflow.com/a/14195313/3781327

    seems like this might also be a legitimate solution, but I'm not sure
    how to make PyQt4 and pyside look the same...
        http://stackoverflow.com/a/8717832
    """

    pyside2uic = None
    if QT_LIB == PYSIDE2:
        try:
            import pyside2uic
        except ImportError:
            # later versions of pyside2 have dropped pyside2uic; use the uic binary instead.
            pyside2uic = None

        if pyside2uic is None:
            pyside2version = tuple(map(int, PySide2.__version__.split(".")))
            if (5, 14) <= pyside2version < (5, 14, 2, 2):
                warnings.warn('For UI compilation, it is recommended to upgrade to PySide >= 5.15', RuntimeWarning, stacklevel=2)

    # get class names from ui file
    import xml.etree.ElementTree as xml
    parsed = xml.parse(uiFile)
    widget_class = parsed.find('widget').get('class')
    form_class = parsed.find('class').text

    # convert ui file to python code
    if pyside2uic is None:
        uic_executable = QT_LIB.lower() + '-uic'
        uipy = subprocess.check_output([uic_executable, uiFile])
    else:
        o = _StringIO()
        with open(uiFile, 'r') as f:
            pyside2uic.compileUi(f, o, indent=0)
        uipy = o.getvalue()

    # execute python code
    pyc = compile(uipy, '<string>', 'exec')
    frame = {}
    exec(pyc, frame)

    # fetch the base_class and form class based on their type in the xml from designer
    form_class = frame['Ui_%s'%form_class]
    base_class = eval('QtWidgets.%s'%widget_class)

    return form_class, base_class


# For historical reasons, pyqtgraph maintains a Qt4-ish interface back when
# there wasn't a QtWidgets module. This _was_ done by monkey-patching all of
# QtWidgets into the QtGui module. This monkey-patching modifies QtGui at a
# global level.
# To avoid this, we now maintain a local "mirror" of QtCore, QtGui and QtWidgets.
# Thus, when monkey-patching happens later on in this file, they will only affect
# the local modules and not the global modules.
def _copy_attrs(src, dst):
    for o in dir(src):
        if not hasattr(dst, o):
            setattr(dst, o, getattr(src, o))

def _mirror_submodules(module: str, dest: str, submodules: list[str]):
    # for each submodule of module, copy attributes from the
    # submodule to a similarly named submodule of the dest module
    spec = find_spec(module)
    if spec is None:
        raise ImportError("Module not found", module)
    elif module in sys.modules:
        origin = sys.modules[module]
    else:
        loader = spec.loader
        # portable for Python 3.4+
        origin = loader.create_module(spec) or ModuleType(module)
        loader.exec_module(origin)

    local = sys.modules[dest]
    for sub in submodules:
        fullname = origin.__name__ + "." + sub
        sub_spec = find_spec(fullname)
        if sub_spec is None:
            raise ImportError("Submodule not found", sub, module)
        else:
            loader = sub_spec.loader
            origin_ns = loader.create_module(sub_spec) or ModuleType(fullname)
            loader.exec_module(origin_ns)
        local_ns = getattr(local, sub)
        _copy_attrs(origin_ns, local_ns)


from . import QtCore, QtGui, QtWidgets, compat

_qt_submodules = "QtCore", "QtGui", "QtWidgets"

_mirror_submodules(QT_LIB, __name__, _qt_submodules)

if QT_LIB == PYQT5:
    # We're using PyQt5 which has a different structure so we're going to use a shim to
    # recreate the Qt4 structure for Qt5

    try:
        from PyQt5 import sip
    except ImportError:
        # some Linux distros package it this way (e.g. Ubuntu)
        import sip
    from PyQt5 import uic

    try:
        from PyQt5 import QtSvg
    except ImportError as err:
        QtSvg = FailedImport(err)
    try:
        from PyQt5 import QtTest
    except ImportError as err:
        QtTest = FailedImport(err)

    VERSION_INFO = 'PyQt5 ' + QtCore.PYQT_VERSION_STR + ' Qt ' + QtCore.QT_VERSION_STR

elif QT_LIB == PYQT6:
    from PyQt6 import sip, uic

    try:
        from PyQt6 import QtSvg
    except ImportError as err:
        QtSvg = FailedImport(err)
    try:
        from PyQt6 import QtOpenGLWidgets
    except ImportError as err:
        QtOpenGLWidgets = FailedImport(err)
    try:
        from PyQt6 import QtTest
    except ImportError as err:
        QtTest = FailedImport(err)

    VERSION_INFO = 'PyQt6 ' + QtCore.PYQT_VERSION_STR + ' Qt ' + QtCore.QT_VERSION_STR

elif QT_LIB == PYSIDE2:
    try:
        from PySide2 import QtSvg
    except ImportError as err:
        QtSvg = FailedImport(err)
    try:
        from PySide2 import QtTest
    except ImportError as err:
        QtTest = FailedImport(err)

    import PySide2
    import shiboken2 as shiboken
    VERSION_INFO = 'PySide2 ' + PySide2.__version__ + ' Qt ' + QtCore.__version__

elif QT_LIB == PYSIDE6:
    try:
        from PySide6 import QtSvg
    except ImportError as err:
        QtSvg = FailedImport(err)
    try:
        from PySide6 import QtOpenGLWidgets
    except ImportError as err:
        QtOpenGLWidgets = FailedImport(err)
    try:
        from PySide6 import QtTest
    except ImportError as err:
        QtTest = FailedImport(err)

    import PySide6
    import shiboken6 as shiboken
    VERSION_INFO = 'PySide6 ' + PySide6.__version__ + ' Qt ' + QtCore.__version__

else:
    raise ValueError("Invalid Qt lib '%s'" % QT_LIB)


if QT_LIB in [PYQT6, PYSIDE6]:
    # We're using Qt6 which has a different structure so we're going to use a shim to
    # recreate the Qt5 structure

    if not isinstance(QtOpenGLWidgets, FailedImport):
        QtWidgets.QOpenGLWidget = QtOpenGLWidgets.QOpenGLWidget

    # PySide6 incorrectly placed QFileSystemModel inside QtWidgets
    if QT_LIB == PYSIDE6 and hasattr(QtWidgets, 'QFileSystemModel'):
        module = getattr(QtWidgets, "QFileSystemModel")
        setattr(QtGui, "QFileSystemModel", module)

else:
    # Shim Qt5 namespace to match Qt6
    module_whitelist = [
        "QAction",
        "QActionGroup",
        "QFileSystemModel",
        "QShortcut",
        "QUndoCommand",
        "QUndoGroup",
        "QUndoStack",
    ]
    for module in module_whitelist:
        attr = getattr(QtWidgets, module)
        setattr(QtGui, module, attr)


# Common to PySide2 and PySide6
if QT_LIB in [PYSIDE2, PYSIDE6]:
    QtVersion = QtCore.__version__
    loadUiType = _loadUiType
    isQObjectAlive = shiboken.isValid

    # PySide does not implement qWait
    if not isinstance(QtTest, FailedImport):
        if not hasattr(QtTest.QTest, 'qWait'):
            @staticmethod
            def qWait(msec):
                start = time.time()
                QtWidgets.QApplication.processEvents()
                while time.time() < start + msec * 0.001:
                    QtWidgets.QApplication.processEvents()
            QtTest.QTest.qWait = qWait

    compat.wrapinstance = shiboken.wrapInstance
    compat.unwrapinstance = lambda x : shiboken.getCppPointer(x)[0]
    compat.voidptr = shiboken.VoidPtr

# Common to PyQt5 and PyQt6
if QT_LIB in [PYQT5, PYQT6]:
    QtVersion = QtCore.QT_VERSION_STR

    # PyQt, starting in v5.5, calls qAbort when an exception is raised inside
    # a slot. To maintain backward compatibility (and sanity for interactive
    # users), we install a global exception hook to override this behavior.
    if sys.excepthook == sys.__excepthook__:
        sys_excepthook = sys.excepthook
        def pyqt_qabort_override(*args, **kwds):
            return sys_excepthook(*args, **kwds)
        sys.excepthook = pyqt_qabort_override
    
    def isQObjectAlive(obj):
        return not sip.isdeleted(obj)
    
    loadUiType = uic.loadUiType

    QtCore.Signal = QtCore.pyqtSignal

    compat.wrapinstance = sip.wrapinstance
    compat.unwrapinstance = sip.unwrapinstance
    compat.voidptr = sip.voidptr

from . import internals

# Alert user if using Qt < 5.15, but do not raise exception
versionReq = [5, 15]
m = re.match(r'(\d+)\.(\d+).*', QtVersion)
if m is not None and list(map(int, m.groups())) < versionReq:
    warnings.warn(
        f"PyQtGraph supports Qt version >= {versionReq[0]}.{versionReq[1]},"
        f" but {QtVersion} detected.",
        RuntimeWarning,
        stacklevel=2
    )

App = QtWidgets.QApplication
# subclassing QApplication causes segfaults on PySide{2, 6} / Python 3.8.7+

QAPP = None
def mkQApp(name=None):
    """
    Creates new QApplication or returns current instance if existing.
    
    ============== ========================================================
    **Arguments:**
    name           (str) Application name, passed to Qt
    ============== ========================================================
    """
    global QAPP

    def onPaletteChange(palette):
        color = palette.base().color()
        app = QtWidgets.QApplication.instance()
        darkMode = color.lightnessF() < 0.5
        app.setProperty('darkMode', darkMode)

    QAPP = QtWidgets.QApplication.instance()
    if QAPP is None:
        # hidpi handling
        qtVersionCompare = tuple(map(int, QtVersion.split(".")))
        if qtVersionCompare > (6, 0):
            # Qt6 seems to support hidpi without needing to do anything so continue
            pass
        elif qtVersionCompare > (5, 14):
            os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
            QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        else:  # qt 5.12 and 5.13
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)

        QAPP = QtWidgets.QApplication(sys.argv or ["pyqtgraph"])
        QAPP.paletteChanged.connect(onPaletteChange)
        QAPP.paletteChanged.emit(QAPP.palette())

    if name is not None:
        QAPP.setApplicationName(name)
    return QAPP


# exec() is used within _loadUiType, so we define as exec_() here and rename in pg namespace
def exec_():
    app = mkQApp()
    return app.exec() if hasattr(app, 'exec') else app.exec_()
