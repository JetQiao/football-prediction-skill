import unittest

from football_prediction.domain import TeamFeatures
from football_prediction.modeling.dixon_coles import build_prediction, dc_tau, predict_from_features


class DixonColesTests(unittest.TestCase):
    def test_matrix_is_normalized(self):
        prediction = build_prediction(1.7, 1.1)
        self.assertAlmostEqual(sum(sum(row) for row in prediction.matrix), 1.0, places=10)
        self.assertAlmostEqual(sum(prediction.probabilities.vector()), 1.0)
        self.assertEqual(len(prediction.top_scores), 5)

    def test_low_score_correction(self):
        self.assertNotEqual(dc_tau(0, 0, 1.4, 1.1, -0.08), 1.0)
        self.assertEqual(dc_tau(2, 2, 1.4, 1.1, -0.08), 1.0)

    def test_features_raise_stronger_home_probability(self):
        strong = TeamFeatures("A", elo=1900, xg_for=1.9, xg_against=0.8, form_index=0.4)
        weak = TeamFeatures("B", elo=1600, xg_for=1.0, xg_against=1.7, form_index=-0.3)
        prediction = predict_from_features(strong, weak)
        self.assertGreater(prediction.probabilities.home, prediction.probabilities.away)


if __name__ == "__main__":
    unittest.main()
