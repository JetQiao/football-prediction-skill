import unittest

from football_prediction.domain import Probability3
from football_prediction.reporting.analysis import derive_markets, half_full, tilt_matrix


class ReportingAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.matrix = (
            (0.12, 0.09, 0.04),
            (0.14, 0.16, 0.07),
            (0.08, 0.09, 0.05),
            (0.03, 0.02, 0.01),
        )
        total = sum(sum(row) for row in self.matrix)
        self.matrix = tuple(tuple(value / total for value in row) for row in self.matrix)
        self.final = Probability3(0.46, 0.28, 0.26)

    def test_tilted_matrix_matches_final_three_way_probabilities(self):
        tilted = tilt_matrix(self.matrix, self.final)
        home = sum(tilted[i][j] for i in range(len(tilted)) for j in range(len(tilted[i])) if i > j)
        draw = sum(tilted[i][i] for i in range(len(tilted)) if i < len(tilted[i]))
        away = sum(tilted[i][j] for i in range(len(tilted)) for j in range(len(tilted[i])) if i < j)
        self.assertAlmostEqual(home, self.final.home)
        self.assertAlmostEqual(draw, self.final.draw)
        self.assertAlmostEqual(away, self.final.away)

    def test_half_full_grid_is_normalized(self):
        grid = half_full(1.55, 1.10)
        self.assertEqual((len(grid), len(grid[0])), (3, 3))
        self.assertAlmostEqual(sum(sum(row) for row in grid), 1.0)
        self.assertTrue(all(0 <= value <= 1 for row in grid for value in row))

    def test_derived_markets_cover_user_facing_play_types(self):
        markets = derive_markets(self.matrix, self.final, 1.55, 1.10, -1)
        self.assertIn("handicap", markets)
        self.assertIn("htft", markets)
        self.assertIn("goals_distribution", markets)
        self.assertEqual(len(markets["htft"]["grid"]), 3)
        self.assertAlmostEqual(
            markets["handicap"]["home"] + markets["handicap"]["draw"] + markets["handicap"]["away"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
