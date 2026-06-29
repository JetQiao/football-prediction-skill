import unittest

from football_prediction.domain import Probability3
from football_prediction.tournament import Fixture, TournamentSimulator


class TournamentTests(unittest.TestCase):
    def test_rank_probabilities_sum_to_one(self):
        fixtures = [
            Fixture("A", "强队", "弱队", Probability3(0.7, 0.2, 0.1)),
            Fixture("A", "强队", "中队", Probability3(0.6, 0.25, 0.15)),
            Fixture("A", "中队", "弱队", Probability3(0.55, 0.25, 0.2)),
        ]
        result = TournamentSimulator(seed=7).simulate(fixtures, runs=500)
        for ranks in result["A"].values():
            self.assertAlmostEqual(sum(ranks.values()), 1.0)

    def test_strategy_only_applies_after_qualification(self):
        simulator = TournamentSimulator()
        self.assertEqual(simulator.strategic_adjustment(1800, 1600, qualification_locked=False), 0)
        self.assertLess(simulator.strategic_adjustment(1800, 1600, qualification_locked=True), 0)


if __name__ == "__main__":
    unittest.main()
