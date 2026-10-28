"""Static regression contracts for the Telegram Mini App's touch-safe layout.

These checks catch the previous regression where a splash-screen optimization
changed the ready app shell from flex to block, hiding the bottom navigation.
They are intentionally dependency-free and run in the normal GitHub CI suite.
"""
from pathlib import Path
import re
import unittest


PUBLIC = Path(__file__).resolve().parents[1] / "public"


class MobileNavigationContract(unittest.TestCase):
    def test_ready_shell_remains_flex_after_launch(self):
        css = (PUBLIC / "styles.css").read_text(encoding="utf-8")
        matches = re.findall(r"body\\.zen-ready\\s+\\.app-shell\\s*\\{([^{}]*)\\}", css)
        self.assertTrue(matches, "Ready-app CSS rule must exist")
        last = matches[-1].replace(" ", "").replace("\\n", "")
        self.assertIn("display:flex!important", last)
        self.assertIn("flex-direction:column!important", last)
        self.assertNotIn("display:block", last)

    def test_main_navigation_has_five_tappable_tabs(self):
        html = (PUBLIC / "index.html").read_text(encoding="utf-8")
        css = (PUBLIC / "styles.css").read_text(encoding="utf-8")
        tabs = re.findall(r'data-tab="(home|earn|friends|wallet|profile)"', html)
        self.assertEqual(tabs, ["home", "earn", "friends", "wallet", "profile"])
        self.assertIn("body.zen-ready .app-shell>.bottom-nav", css)
        self.assertIn("pointer-events:auto", css)
        self.assertIn("min-height:48px", css)

    def test_only_active_screen_scrolls_between_header_and_nav(self):
        css = (PUBLIC / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".app-shell>.screen.active", css)
        self.assertIn("overflow-y:auto", css)
        self.assertIn(".app-shell>.topbar", css)
        self.assertIn("body.zen-loading .app-shell{display:none!important}", css)


if __name__ == "__main__":
    unittest.main()
