import tempfile
import unittest
from pathlib import Path

from football_prediction.modeling.dixon_coles import DixonColesModel
from football_prediction.modeling.registry import ModelBundle, ModelMetadata, ModelRegistry


class ModelRegistryTests(unittest.TestCase):
    @staticmethod
    def _bundle(version: str, competition: str, trained_until: str, aliases=()):
        return ModelBundle(
            ModelMetadata(
                version=version,
                competition=competition,
                aliases=tuple(aliases),
                trained_until=trained_until,
                sample_size=200,
                calibration_status="validated",
                calibration_sample_size=150,
            ),
            DixonColesModel(teams=("A", "B")),
        )

    def test_only_promoted_models_resolve_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ModelRegistry(Path(temp))
            challenger = self._bundle("challenger", "英超", "2026-05-01")
            registry.register(challenger)
            self.assertIsNone(registry.resolve("英超", as_of="2026-06-01T10:00:00+08:00"))
            self.assertEqual(
                registry.resolve(
                    "英超",
                    as_of="2026-06-01T10:00:00+08:00",
                    allow_challenger=True,
                ).metadata.version,
                "challenger",
            )

    def test_promoting_alias_unpromotes_previous_production_model(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ModelRegistry(Path(temp))
            registry.register(self._bundle("old", "Premier League", "2026-04-01", ("英超",)), promote=True)
            registry.register(self._bundle("new", "英超", "2026-05-01", ("Premier League",)), promote=True)
            rows = {row["version"]: row for row in registry.list()}
            self.assertFalse(rows["old"]["promoted"])
            self.assertTrue(rows["new"]["promoted"])
            self.assertEqual(
                registry.resolve("Premier League", as_of="2026-06-01T10:00:00+08:00").metadata.version,
                "new",
            )

    def test_same_day_model_is_not_visible_to_prediction(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ModelRegistry(Path(temp))
            registry.register(self._bundle("same-day", "英超", "2026-06-01"), promote=True)
            self.assertIsNone(registry.resolve("英超", as_of="2026-06-01T18:00:00+08:00"))


if __name__ == "__main__":
    unittest.main()
