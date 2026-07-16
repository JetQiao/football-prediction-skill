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
            self.assertEqual(report.schema_version, "2.1")
            self.assertTrue(all(prediction.direction_reason for prediction in report.predictions))
            self.assertTrue(all(prediction.value_reason for prediction in report.predictions))
            self.assertTrue(json_path.exists())
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("竞彩足球", html)
            self.assertIn("半全场", html)
            self.assertIn("官方玩法 5/5", html)
            self.assertIn('id="matchList"', html)
            self.assertIn('data-tab="prices"', html)
            self.assertIn('class="match-dialog"', html)
            self.assertIn("概率与价格工作台", html)
            self.assertIn("方向判断", html)
            self.assertIn("价值判断", html)
            self.assertIn("未独立验证", html)
            self.assertNotIn(">弃权<", html)
            self.assertIn("模型与市场概率对照", html)
            self.assertIn("官方 SP 去水", html)
            self.assertIn("演示数据", html)
            self.assertNotIn("WORLD CUP AI HUB", html)
            self.assertNotIn("MATCHDAY CONTROL", html)
            self.assertIn('type="application/json"', html)
            self.assertNotIn("https://cdn", html)
            self.assertNotIn("nth-of-type(n+2)", html)
            manifests = list((root / "out").glob("manifest_*.json"))
            self.assertTrue(manifests)
            manifest = manifests[0].read_text(encoding="utf-8")
            self.assertIn('"direction_counts"', manifest)
            self.assertIn('"value_counts"', manifest)


if __name__ == "__main__":
    unittest.main()
