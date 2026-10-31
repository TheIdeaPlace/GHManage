"""The main window's layout, as JAWS hears it on Windows (JAWS test of
31 October 2026).

- A text box takes its name from the label just before it, so the Details
  label is made before the details text. Made after, JAWS called the box
  "details_panel" and Insert+Tab gave no name.
- A wx.Panel's or wx.SplitterWindow's name becomes its window text, which
  JAWS reads on the way into the details text and on coming back to the
  window ("main_splitter, right_panel, splitterWindow, details_panel"). The
  ones that only lay things out have none.

Checked in the source: building the real window here would put it on the
screen of whoever runs the tests.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "ghviewer.py").read_text(encoding="utf-8")


def _build_ui() -> str:
    start = SOURCE.index("self.main_splitter = wx.SplitterWindow(")
    end = SOURCE.index("self.splitter.SplitHorizontally(", start)
    return SOURCE[start:end]


def test_the_details_label_comes_before_the_details_text():
    ui = _build_ui()
    label = ui.index('wx.StaticText(details_panel, label="Details")')
    box = ui.index("self.details_text = wx.TextCtrl(")
    assert label < box


def test_the_details_text_is_named_details():
    assert '_name(self.details_text, "Details")' in _build_ui()


def test_layout_panels_and_splitters_have_no_name():
    made = re.findall(r"wx\.(?:Panel|SplitterWindow)\(([^\n]*)\)", _build_ui())
    assert len(made) >= 6
    for args in made:
        assert 'name=""' in args, args
