import tempfile
import unittest
from datetime import date
from pathlib import Path

from football_prediction.config import AppPaths, Settings
from football_prediction.demo import demo_matches
from football_prediction.pipeline import DailyPipeline


class PipelineTests(unittest.TestCase):
    def test_demo_writes_self_contained_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(paths=AppPaths(root / "data", root / "cache", root / "config"))
            report, json_path, html_path = DailyPipeline(settings).run(
                date(2026, 6, 29), matches=demo_matches(date(2026, 6, 29)), output_dir=root / "out"
            )
            self.assertEqual(len(report.predictions), 3)
            self.assertTrue(json_path.exists())
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("竞彩足球", html)
            self.assertIn("半全场", html)
            self.assertIn("官方玩法 5/5", html)
            self.assertIn('data-tab="markets"', html)
            self.assertIn("MATCHDAY CONTROL", html)
            self.assertIn("指挥中心", html)
            self.assertIn("MATCH CENTER", html)
            self.assertIn("模型与市场概率对照", html)
            self.assertIn("官方 SP 去水", html)
            self.assertIn("DEMO DATA DETECTED", html)
            self.assertNotIn("WORLD CUP AI HUB", html)
            self.assertIn('type="application/json"', html)
            self.assertNotIn("https://cdn", html)
            self.assertNotIn("nth-of-type(n+2)", html)
            self.assertTrue(list((root / "out").glob("manifest_*.json")))


if __name__ == "__main__":
    unittest.main()
