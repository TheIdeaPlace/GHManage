"""speech.py: the UIA provider GHManage serves so its notifications reach
screen readers (#65). Whether they are spoken was measured with NVDA and
Narrator in the test VM; these check the provider is a well-formed COM object
and that the window serves it, so a change that breaks either fails here."""

from __future__ import annotations

import ctypes
import os
import sys

import pytest

import speech

windows = pytest.mark.skipif(sys.platform != "win32", reason="UI Automation is Windows only")


def _call(pointer, index, prototype, *args):
    """Call entry ``index`` of the COM object at ``pointer``'s vtable."""
    vtable = ctypes.cast(ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0],
                         ctypes.POINTER(ctypes.c_void_p))
    return prototype(vtable[index])(pointer, *args)


@windows
def test_the_provider_answers_as_iraw_element_provider_simple():
    p = speech._Provider(0, "GHManage announcements")
    out = ctypes.c_void_p()
    for iid in ("00000000-0000-0000-C000-000000000046", "d6dd68d1-86fd-4332-8666-9abedea2d24c"):
        guid = speech._GUID.of(iid)
        assert _call(p.pointer, 0, speech._QI, ctypes.byref(guid), ctypes.byref(out)) == 0
        assert out.value == p.pointer
    other = speech._GUID.of("12345678-1234-1234-1234-123456789abc")
    assert _call(p.pointer, 0, speech._QI, ctypes.byref(other), ctypes.byref(out)) == speech.E_NOINTERFACE
    assert not out.value

    options = ctypes.c_int()
    assert _call(p.pointer, 3, speech._OPTIONS, ctypes.byref(options)) == 0
    assert options.value == speech.PROVIDER_OPTIONS

    pattern = ctypes.c_void_p(1)
    assert _call(p.pointer, 4, speech._PATTERN, 10000, ctypes.byref(pattern)) == 0
    assert not pattern.value


@windows
def test_the_provider_is_named_and_kept_out_of_the_control_and_content_views():
    p = speech._Provider(0, "GHManage announcements")
    ole = speech._windows_api()[1]
    v = speech._VARIANT()
    assert _call(p.pointer, 5, speech._PROPERTY, speech.UIA_NAME, ctypes.byref(v)) == 0
    assert v.vt == speech.VT_BSTR
    assert ctypes.wstring_at(v.value) == "GHManage announcements"
    ole.SysFreeString(v.value)
    for prop in (speech.UIA_IS_CONTROL_ELEMENT, speech.UIA_IS_CONTENT_ELEMENT):
        v = speech._VARIANT()
        _call(p.pointer, 5, speech._PROPERTY, prop, ctypes.byref(v))
        assert v.vt == speech.VT_BOOL and not v.value
    v = speech._VARIANT()
    _call(p.pointer, 5, speech._PROPERTY, 30001, ctypes.byref(v))  # BoundingRectangle
    assert v.vt == speech.VT_EMPTY


def test_no_window_means_no_speaker():
    n = speech.UiaNotifier(0)
    assert n.provider is None
    assert not n.notify("moved", True)
    n.close()  # harmless


def test_mac_announcement_off_a_mac_is_refused_quietly():
    if sys.platform == "darwin":
        pytest.skip("on a Mac it would ask VoiceOver")
    assert speech.voiceover_announce("moved", True, "result") is False


if os.environ.get("CI"):
    import wx
else:
    wx = pytest.importorskip("wx")


@pytest.fixture(scope="module")
def frame():
    app = wx.App(False)
    f = wx.Frame(None)
    yield f
    f.Destroy()
    app.Destroy()


@windows
def test_the_window_serves_the_provider_and_lets_go_when_destroyed(frame):
    window = wx.Window(frame, size=(1, 1))
    window.Hide()
    n = speech.UiaNotifier(window.GetHandle())
    assert n.provider is not None
    user32 = ctypes.WinDLL("user32")
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    # UiaRootObjectId is answered with a provider; other ids are not.
    assert user32.SendMessageW(window.GetHandle(), speech.WM_GETOBJECT, 0, speech.UIA_ROOT_OBJECT_ID)
    # OBJID_CLIENT is left to the window as before, for MSAA.
    assert not user32.SendMessageW(window.GetHandle(), speech.WM_GETOBJECT, 0, -4)
    # Raising never fails, whether or not anything is listening.
    assert n.notify("Author moved above Message.", True) in (True, False)
    assert n.notify("Loading.", False) in (True, False)
    window.Destroy()
    assert n.provider is None
    assert not n.notify("after", True)


@windows
def test_speaker_for_platform_on_windows(frame):
    window = wx.Window(frame, size=(1, 1))
    window.Hide()
    try:
        speak = speech.speaker_for_platform(window.GetHandle())
        assert callable(speak)
        assert speech.speaker_for_platform(0) is None
    finally:
        window.Destroy()
