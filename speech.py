"""Handing ``announce``'s messages to the screen reader.

**Windows: UI Automation notifications.** The message is raised as a UIA
notification event, and whichever screen reader is running decides how to
speak it, with its own voice, rate and queue. No code per screen reader,
nothing bundled, and silence when none is listening.

WPF raises these from a control's AutomationPeer. wx windows are Win32 and
expose MSAA, not UIA, and a notification raised from the stand-in provider
``UiaHostProviderFromHwnd`` gives a plain window is never delivered: NVDA's
UIA debug log showed no event at all (#65). What works, as in Firefox, is a
real provider served by a window of our own:

- ``UiaNotifier`` subclasses one hidden child window, made for the purpose,
  so it answers ``WM_GETOBJECT`` for ``UiaRootObjectId`` with a minimal
  ``IRawElementProviderSimple``, written here with ctypes;
- notifications are raised from that provider.

Measured in the test VM: NVDA 2026.2 and Narrator both spoke them, from the
main window and while a modal dialog had focus. The provider is neither a
control nor a content element, so moving around finds nothing new. Never
serve it from the frame itself: that took over the window's UIA name.

**macOS: a VoiceOver announcement.** ``NSAccessibilityAnnouncementRequested``
posted on the application, through ctypes into the Objective-C runtime
(from The Chat Place's ``ui/mac_a11y.py``). Only while VoiceOver is on.

**macOS: control labels** (#69, ``set_label``, also from The Chat Place).
wx's ``SetName()`` reaches nothing native on a Mac: every ``wx.TextCtrl``,
``wx.ListBox`` and ``wx.Choice`` reports ``accessibilityLabel == nil`` however
it was named, so VoiceOver read a box's contents and never its label, and
``SetAccessible()`` is Windows-only. So the label is set on the native view
through NSAccessibility. Buttons and check boxes need no help: AppKit names
them from their title.

Nothing here imports wx, so this can move to app-kit with ``announce``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import functools
import sys
import uuid
from ctypes import POINTER, byref, c_int, c_long, c_ulong, c_void_p
from typing import Callable

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

# ── Windows ─────────────────────────────────────────────────────────────

# NotificationKind and NotificationProcessing (UIAutomationCore.h). NVDA
# cancels what it is saying for either MostRecent kind, and queues
# CurrentThenMostRecent behind it.
KIND_OTHER = 4
PROCESSING_IMPORTANT_MOST_RECENT = 1
PROCESSING_CURRENT_THEN_MOST_RECENT = 4
# One activity per category: a screen reader may keep only the newest
# pending notification of an activity, and a status mustn't replace a result.
ACTIVITY_PREFIX = "GHManage."

WM_GETOBJECT = 0x003D
WM_NCDESTROY = 0x0082
UIA_ROOT_OBJECT_ID = -25
S_OK = 0
E_NOINTERFACE = c_long(0x80004002).value
PROVIDER_OPTIONS = 0x2 | 0x20  # ServerSideProvider | UseComThreading

UIA_CONTROL_TYPE = 30003
UIA_NAME = 30005
UIA_IS_CONTROL_ELEMENT = 30016
UIA_IS_CONTENT_ELEMENT = 30017
UIA_PROVIDER_DESCRIPTION = 30107
UIA_CUSTOM_CONTROL_TYPE = 50025
VT_EMPTY, VT_I4, VT_BSTR, VT_BOOL = 0, 3, 8, 11


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, text: str) -> "_GUID":
        g = cls()
        ctypes.memmove(byref(g), uuid.UUID(text).bytes_le, 16)
        return g


class _VARIANT(ctypes.Structure):
    # vt, three reserved words, then the value: 16 bytes on 32-bit, 24 on 64.
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("value", c_void_p), ("pad", c_void_p)]


_IIDS = {bytes(_GUID.of(i).data) for i in (
    "00000000-0000-0000-C000-000000000046",   # IUnknown
    "d6dd68d1-86fd-4332-8666-9abedea2d24c",   # IRawElementProviderSimple
)}

_api = None  # the loaded functions, or False once loading failed


def _windows_api():
    """(UIAutomationCore, oleaut32, comctl32, SUBCLASSPROC), or None."""
    global _api
    if _api is None:
        _api = False
        if IS_WINDOWS:
            try:
                from ctypes import wintypes as w
                core = ctypes.WinDLL("UIAutomationCore.dll")
                ole = ctypes.WinDLL("oleaut32.dll")
                comctl = ctypes.WinDLL("comctl32.dll")
                lresult = ctypes.c_ssize_t
                # AttributeError here means Windows older than 10 1709.
                core.UiaRaiseNotificationEvent.argtypes = [c_void_p, c_int, c_int,
                                                           c_void_p, c_void_p]
                core.UiaRaiseNotificationEvent.restype = c_long
                core.UiaReturnRawElementProvider.argtypes = [w.HWND, w.WPARAM, w.LPARAM,
                                                             c_void_p]
                core.UiaReturnRawElementProvider.restype = lresult
                core.UiaHostProviderFromHwnd.argtypes = [w.HWND, POINTER(c_void_p)]
                core.UiaHostProviderFromHwnd.restype = c_long
                core.UiaDisconnectProvider.argtypes = [c_void_p]
                core.UiaDisconnectProvider.restype = c_long
                core.UiaClientsAreListening.restype = w.BOOL
                ole.SysAllocString.argtypes = [ctypes.c_wchar_p]
                ole.SysAllocString.restype = c_void_p
                ole.SysFreeString.argtypes = [c_void_p]
                ole.SysFreeString.restype = None
                subclass_proc = ctypes.WINFUNCTYPE(lresult, w.HWND, w.UINT, w.WPARAM,
                                                   w.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
                comctl.SetWindowSubclass.argtypes = [w.HWND, subclass_proc, ctypes.c_size_t,
                                                     ctypes.c_size_t]
                comctl.SetWindowSubclass.restype = w.BOOL
                comctl.RemoveWindowSubclass.argtypes = [w.HWND, subclass_proc, ctypes.c_size_t]
                comctl.RemoveWindowSubclass.restype = w.BOOL
                comctl.DefSubclassProc.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
                comctl.DefSubclassProc.restype = lresult
                _api = (core, ole, comctl, subclass_proc)
            except (OSError, AttributeError):
                _api = False
    return _api or None


if IS_WINDOWS:
    _QI = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(_GUID), POINTER(c_void_p))
    _REF = ctypes.WINFUNCTYPE(c_ulong, c_void_p)
    _OPTIONS = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(c_int))
    _PATTERN = ctypes.WINFUNCTYPE(c_long, c_void_p, c_int, POINTER(c_void_p))
    _PROPERTY = ctypes.WINFUNCTYPE(c_long, c_void_p, c_int, POINTER(_VARIANT))
    _HOST = ctypes.WINFUNCTYPE(c_long, c_void_p, POINTER(c_void_p))


class _Provider:
    """IRawElementProviderSimple for the helper window, built by hand as a
    vtable of ctypes callbacks. Python owns its lifetime (the
    ``UiaNotifier`` keeps it), so the reference count is only reported.
    """

    def __init__(self, hwnd: int, name: str) -> None:
        self.hwnd = hwnd
        self.name = name
        self._refs = 1
        self._callbacks = [_QI(self._query), _REF(self._add_ref), _REF(self._release),
                           _OPTIONS(self._options), _PATTERN(self._pattern),
                           _PROPERTY(self._property), _HOST(self._host)]
        self._vtable = (c_void_p * 7)(*[ctypes.cast(f, c_void_p) for f in self._callbacks])
        self._object = (c_void_p * 1)(ctypes.addressof(self._vtable))
        self.pointer = ctypes.addressof(self._object)

    def _query(self, this, iid, out):
        if bytes(iid[0].data) in _IIDS:
            out[0] = self.pointer
            self._refs += 1
            return S_OK
        out[0] = None
        return E_NOINTERFACE

    def _add_ref(self, this):
        self._refs += 1
        return self._refs

    def _release(self, this):
        self._refs = max(self._refs - 1, 1)
        return self._refs

    def _options(self, this, out):
        out[0] = PROVIDER_OPTIONS
        return S_OK

    def _pattern(self, this, pattern_id, out):
        out[0] = None
        return S_OK

    def _property(self, this, property_id, out):
        v = out[0]
        v.vt = VT_EMPTY
        if property_id in (UIA_NAME, UIA_PROVIDER_DESCRIPTION):
            # The caller frees the BSTR.
            v.vt, v.value = VT_BSTR, _windows_api()[1].SysAllocString(self.name)
        elif property_id == UIA_CONTROL_TYPE:
            v.vt, v.value = VT_I4, UIA_CUSTOM_CONTROL_TYPE
        elif property_id in (UIA_IS_CONTROL_ELEMENT, UIA_IS_CONTENT_ELEMENT):
            v.vt, v.value = VT_BOOL, 0  # out of the control and content views
        return S_OK

    def _host(self, this, out):
        host = c_void_p()
        result = _windows_api()[0].UiaHostProviderFromHwnd(self.hwnd, byref(host))
        out[0] = host.value
        return result


class UiaNotifier:
    """Raises UIA notifications from a window the app sets aside for them:
    hidden, never focused, a child of the main window."""

    def __init__(self, hwnd: int, name: str = "GHManage announcements") -> None:
        self.hwnd = hwnd
        self.provider: _Provider | None = None
        self._retired: list[_Provider] = []
        api = _windows_api()
        if api is None or not hwnd:
            return
        core, _ole, comctl, subclass_proc = api
        provider = _Provider(hwnd, name)

        def window_proc(h, msg, wparam, lparam, _id, _data):
            if (msg == WM_GETOBJECT and c_long(lparam).value == UIA_ROOT_OBJECT_ID
                    and self.provider is not None):
                return core.UiaReturnRawElementProvider(h, wparam, lparam,
                                                        self.provider.pointer)
            if msg == WM_NCDESTROY:
                self.close()
            return comctl.DefSubclassProc(h, msg, wparam, lparam)

        self._proc = subclass_proc(window_proc)
        if comctl.SetWindowSubclass(hwnd, self._proc, 1, 0):
            self.provider = provider

    def close(self) -> None:
        """Have UIA let go of the provider, for when the window goes."""
        api = _windows_api()
        if api is None or self.provider is None:
            return
        core, _ole, comctl, _ = api
        provider, self.provider = self.provider, None
        self._retired.append(provider)  # a call from UIA may still be on its way
        core.UiaReturnRawElementProvider(self.hwnd, 0, 0, None)
        core.UiaDisconnectProvider(provider.pointer)
        comctl.RemoveWindowSubclass(self.hwnd, self._proc, 1)

    def notify(self, text: str, interrupt: bool, category: str = "result") -> bool:
        """Raise ``text`` as a notification. True if a listening client was
        sent it. ``interrupt`` cuts off what the screen reader is saying;
        otherwise it follows what is being said."""
        api = _windows_api()
        if api is None or self.provider is None or not text:
            return False
        core, ole, _, _ = api
        if not core.UiaClientsAreListening():
            return False
        message = ole.SysAllocString(text)
        activity = ole.SysAllocString(ACTIVITY_PREFIX + category)
        try:
            processing = (PROCESSING_IMPORTANT_MOST_RECENT if interrupt
                          else PROCESSING_CURRENT_THEN_MOST_RECENT)
            return core.UiaRaiseNotificationEvent(self.provider.pointer, KIND_OTHER,
                                                  processing, message, activity) >= 0
        finally:
            ole.SysFreeString(message)
            ole.SysFreeString(activity)


# ── macOS ───────────────────────────────────────────────────────────────

_objc = None  # libobjc, or False once loading failed

# NSAccessibilityPriorityLevel.
MAC_PRIORITY_LOW = 10     # after what VoiceOver is saying
MAC_PRIORITY_HIGH = 90    # interrupts it


def _runtime():
    global _objc
    if _objc is None:
        _objc = False
        if IS_MACOS:
            try:
                path = ctypes.util.find_library("objc")
                lib = ctypes.cdll.LoadLibrary(path) if path else None
            except OSError:
                lib = None
            if lib is not None:
                lib.sel_registerName.restype = ctypes.c_void_p
                lib.sel_registerName.argtypes = [ctypes.c_char_p]
                lib.objc_getClass.restype = ctypes.c_void_p
                lib.objc_getClass.argtypes = [ctypes.c_char_p]
                _objc = lib
    return _objc or None


@functools.lru_cache(maxsize=None)
def _msg_send(restype, argtypes):
    # objc_msgSend cast to each method's own prototype: calling it through the
    # wrong one is undefined on arm64.
    signature = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
    return signature(ctypes.cast(_runtime().objc_msgSend, ctypes.c_void_p).value)


def _send(obj, selector, *args, restype=ctypes.c_void_p, argtypes=()):
    sel = _runtime().sel_registerName(selector.encode())
    return _msg_send(restype, tuple(argtypes))(obj, sel, *args)


def _class(name: str):
    return _runtime().objc_getClass(name.encode())


def _nsstring(text: str):
    return _send(_class("NSString"), "stringWithUTF8String:", text.encode("utf-8"),
                 argtypes=(ctypes.c_char_p,))


def voiceover_announce(text: str, interrupt: bool, category: str = "result") -> bool:
    """Ask VoiceOver to say ``text``. True if it was asked; False when
    VoiceOver is off or the request couldn't be made."""
    if not IS_MACOS or not text or _runtime() is None:
        return False
    try:
        workspace = _send(_class("NSWorkspace"), "sharedWorkspace")
        if not _send(workspace, "isVoiceOverEnabled", restype=ctypes.c_bool):
            return False
        appkit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")

        def constant(name):
            return ctypes.c_void_p.in_dll(appkit, name).value

        info = _send(_class("NSMutableDictionary"), "dictionary")
        priority = _send(_class("NSNumber"), "numberWithInteger:",
                         MAC_PRIORITY_HIGH if interrupt else MAC_PRIORITY_LOW,
                         argtypes=(ctypes.c_long,))
        for key, value in (("NSAccessibilityAnnouncementKey", _nsstring(text)),
                           ("NSAccessibilityPriorityKey", priority)):
            _send(info, "setObject:forKey:", value, constant(key),
                  argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        post = appkit.NSAccessibilityPostNotificationWithUserInfo
        post.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        post.restype = None
        # AppKit wants the application element here, not a view.
        application = _send(_class("NSApplication"), "sharedApplication")
        post(application, constant("NSAccessibilityAnnouncementRequestedNotification"), info)
        return True
    except Exception:  # noqa: BLE001 - never break the app over speech
        return False


def _responds(obj, selector: str) -> bool:
    sel = _runtime().sel_registerName(selector.encode())
    return bool(_send(obj, "respondsToSelector:", ctypes.c_void_p(sel),
                      restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)))


def _to_str(nsstring) -> str | None:
    if not nsstring:
        return None
    pointer = _send(nsstring, "UTF8String", restype=ctypes.c_char_p)
    return pointer.decode("utf-8") if pointer else None


def _target_view(window):
    """The native view VoiceOver focuses for ``window``, or None.

    ``GetHandle()`` isn't always it. A multi-line ``wx.TextCtrl`` is a scroll
    view around an ``NSTextView``, a ``wx.ListBox`` and the Mac item list
    (``wx.dataview.DataViewListCtrl``) a scroll view around a table, and
    VoiceOver lands on the inner view. So when the handle has a
    ``documentView``, that is what gets the label.
    """
    if _runtime() is None:
        return None
    try:
        handle = window.GetHandle()
    except (AttributeError, RuntimeError):
        return None
    if not handle:
        return None
    view = ctypes.c_void_p(handle)
    if _responds(view, "documentView"):
        inner = _send(view, "documentView")
        if inner:
            return ctypes.c_void_p(inner)
    return view


def set_label(window, label: str) -> bool:
    """Give ``window`` (anything with ``GetHandle()``) the name VoiceOver reads.
    True if it was applied.

    False, never an exception, off macOS or on a control with no native view:
    a missing name mustn't take the window down with it.
    """
    if not IS_MACOS or not label:
        return False
    try:
        view = _target_view(window)
        if view is None or not _responds(view, "setAccessibilityLabel:"):
            return False
        _send(view, "setAccessibilityLabel:", ctypes.c_void_p(_nsstring(label)),
              argtypes=(ctypes.c_void_p,))
        return True
    except Exception:  # noqa: BLE001 - never break the window over a name
        return False


def get_label(window) -> str | None:
    """The name VoiceOver would read for ``window``, or None. For tests, and
    for checking a control reported as unlabelled."""
    if not IS_MACOS:
        return None
    try:
        view = _target_view(window)
        if view is None or not _responds(view, "accessibilityLabel"):
            return None
        return _to_str(_send(view, "accessibilityLabel"))
    except Exception:  # noqa: BLE001
        return None


# ── Choosing one ────────────────────────────────────────────────────────

# Every UiaNotifier made, for the life of the process: its window is
# subclassed to a ctypes callback that must outlive any speaker holding it.
_notifiers: list[UiaNotifier] = []


def speaker_for_platform(helper_hwnd: int = 0) -> Callable[[str, bool, str], bool] | None:
    """The speaker for ``announce.Announcer.speaker`` on this platform, or
    None where there is none. On Windows, ``helper_hwnd`` is the hidden
    window set aside for ``UiaNotifier``."""
    if IS_WINDOWS:
        notifier = UiaNotifier(helper_hwnd)
        _notifiers.append(notifier)
        return notifier.notify if notifier.provider is not None else None
    if IS_MACOS:
        return voiceover_announce
    return None
