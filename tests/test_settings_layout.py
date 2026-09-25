"""Small desktops and enlarged fonts must leave Settings usable."""
import os
import unittest
from types import SimpleNamespace

import harness


class SettingsLayout(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("settings_layout")
        self.root = self.gm.tk.Tk()
        self.root.withdraw()
        self.scaling = self.root.tk.call("tk", "scaling")
        self.root.tk.call("tk", "scaling", 144 / 72)
        self.gm.monitors = lambda: [((0, 0, 800, 720), (0, 0, 800, 680))]
        self.app = SimpleNamespace(open_performance=lambda: None,
                                   tray=SimpleNamespace(emergency_registered=True))
        self.window = self.gm.SettingsWindow(self.root, self.app)
        self.window.win.withdraw()
        self.root.update_idletasks()

    def tearDown(self):
        self.root.tk.call("tk", "scaling", self.scaling)
        self.root.destroy()
        for name, _ in harness._FILES:
            path = getattr(self.gm, name)
            if os.path.exists(path):
                os.remove(path)

    def descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.descendants(child)

    def test_hidden_settings_stays_hidden_and_fits_small_work_area(self):
        self.assertEqual(self.window.win.state(), "withdrawn")
        self.assertLessEqual(self.window.win.winfo_width(), 800)
        self.assertLessEqual(self.window.win.winfo_height(), 640)
        self.assertTrue(all(self.window.win.resizable()))

    def test_footer_and_every_tab_remain_reachable_when_resized(self):
        win = self.window.win
        win.geometry("640x540")
        win.deiconify()
        self.root.update()
        tabs = next(w for w in self.descendants(win) if isinstance(w, self.gm.ttk.Notebook))
        for tab in tabs.tabs():
            tabs.select(tab)
            self.root.update()
            for button in self.descendants(win):
                if isinstance(button, self.gm.tk.Button) and button.cget("text") in ("Apply", "Close"):
                    self.assertTrue(button.winfo_ismapped(), button.cget("text"))
                    bottom = button.winfo_rooty() - win.winfo_rooty() + button.winfo_height()
                    self.assertLessEqual(bottom, win.winfo_height())
            self.assertTrue(self.window.status.winfo_ismapped())
            page = win.nametowidget(tab)
            canvases = [w for w in self.descendants(page) if isinstance(w, self.gm.tk.Canvas)]
            self.assertTrue(canvases, "A constrained tab needs a scrollable viewport")
            view = canvases[0]
            view.yview_moveto(1.0)
            view.xview_moveto(1.0)
            self.root.update()
            self.assertAlmostEqual(view.yview()[1], 1.0, places=2)
            self.assertAlmostEqual(view.xview()[1], 1.0, places=2)

    def test_enlarged_fonts_keep_action_labels_at_minimum_width(self):
        self.window.win.destroy()
        self.root.tk.call("tk", "scaling", 240 / 72)
        self.window = self.gm.SettingsWindow(self.root, self.app)
        self.window.win.withdraw()
        self.root.update_idletasks()
        self.window.win.geometry("320x400")
        self.window.win.deiconify()
        self.root.update()
        for button in self.descendants(self.window.win):
            if isinstance(button, self.gm.tk.Button) and button.cget("text") in ("Apply", "Close"):
                self.assertTrue(button.winfo_ismapped())
                self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())


if __name__ == "__main__":
    unittest.main()
