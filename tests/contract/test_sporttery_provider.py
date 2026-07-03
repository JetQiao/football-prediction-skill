import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from football_prediction.providers.base import ProviderError
from football_prediction.providers.sporttery import SportteryProvider

FIXTURES = Path(__file__).parents[1] / "fixtures"


class SportteryProviderTests(unittest.TestCase):
    def test_parse_official_contract(self):
        payload = json.loads((FIXTURES / "sporttery_official.json").read_text(encoding="utf-8"))
        matches = SportteryProvider.parse_official(payload, "2026-06-29")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].match_no, "周一001")
        self.assertAlmostEqual(matches[0].sporttery_odds.home, 1.92)
        self.assertEqual(len(matches[0].sporttery_markets), 5)
        self.assertEqual(matches[0].market("hafu").get("HH").label, "胜/胜")
        self.assertEqual(matches[0].market("ttg").get("7+").odds, 26.0)

    def test_parse_api_contract(self):
        payload = json.loads((FIXTURES / "sporttery_api.json").read_text(encoding="utf-8"))
        matches = SportteryProvider.parse_sporttery_api(payload, "2026-06-29")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].home, "海港城")
        self.assertEqual(matches[0].handicap, -1)
        self.assertEqual(len(matches[0].sporttery_markets), 5)
        self.assertEqual(matches[0].market("crs").get("1:0").odds, 7.8)

    def test_keeps_matches_when_had_is_not_on_sale(self):
        payload = {
            "value": {
                "lastUpdateTime": "2026-07-03 12:00:00",
                "matchInfoList": [
                    {
                        "businessDate": "2026-07-03",
                        "matchCount": 2,
                        "subMatchList": [
                            {
                                "matchId": 1,
                                "matchNumStr": "周五001",
                                "businessDate": "2026-07-03",
                                "matchDate": "2026-07-04",
                                "matchTime": "02:00:00",
                                "leagueAbbName": "测试联赛",
                                "homeTeamAbbName": "甲队",
                                "awayTeamAbbName": "乙队",
                                "had": {"h": "1.90", "d": "3.20", "a": "3.80"},
                            },
                            {
                                "matchId": 2,
                                "matchNumStr": "周五002",
                                "businessDate": "2026-07-03",
                                "matchDate": "2026-07-04",
                                "matchTime": "06:00:00",
                                "leagueAbbName": "测试联赛",
                                "homeTeamAbbName": "丙队",
                                "awayTeamAbbName": "丁队",
                                "had": {},
                                "hhad": {
                                    "goalLineValue": "-2",
                                    "h": "2.22",
                                    "d": "3.62",
                                    "a": "2.48",
                                },
                            },
                        ],
                    }
                ],
            }
        }

        matches = SportteryProvider.parse_official(payload, "2026-07-03")

        self.assertEqual(len(matches), 2)
        self.assertIsNone(matches[1].sporttery_odds)
        self.assertEqual(matches[1].market("hhad").line, -2)

    def test_keeps_fixture_before_any_market_opens(self):
        payload = {
            "value": {
                "matchInfoList": [
                    {
                        "businessDate": "2026-07-03",
                        "matchCount": 1,
                        "subMatchList": [
                            {
                                "matchId": 3,
                                "matchNumStr": "周五003",
                                "businessDate": "2026-07-03",
                                "matchDate": "2026-07-04",
                                "matchTime": "09:00:00",
                                "leagueAbbName": "测试联赛",
                                "homeTeamAbbName": "戊队",
                                "awayTeamAbbName": "己队",
                                "matchStatus": "NotSelling",
                            }
                        ],
                    }
                ]
            }
        }

        matches = SportteryProvider.parse_official(payload, "2026-07-03")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].sporttery_markets, ())
        self.assertEqual(matches[0].match_status, "NotSelling")

    def test_network_failure_falls_back_to_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            (cache / "snapshot.json").write_text(
                (FIXTURES / "sporttery_api.json").read_text(encoding="utf-8"), encoding="utf-8"
            )
            provider = SportteryProvider(cache_dir=cache)
            with patch("football_prediction.providers.sporttery.fetch_json", side_effect=ProviderError("HTTP 567")):
                from datetime import date

                matches = provider.fetch_matches(date(2026, 6, 29))
            self.assertEqual(len(matches), 1)
            self.assertEqual(provider.active_source, "stale-cache")
            self.assertTrue(provider.warnings)

    def test_official_source_retries_without_proxy(self):
        payload = json.loads((FIXTURES / "sporttery_official.json").read_text(encoding="utf-8"))
        provider = SportteryProvider()
        with patch(
            "football_prediction.providers.sporttery.fetch_json",
            side_effect=[ProviderError("HTTP 567"), payload],
        ) as fetch:
            from datetime import date

            matches = provider.fetch_matches(date(2026, 6, 29))

        self.assertEqual(len(matches), 1)
        self.assertEqual([call.kwargs["no_proxy"] for call in fetch.call_args_list], [False, True])
        self.assertIn("已绕过代理直连", " ".join(provider.warnings))


if __name__ == "__main__":
    unittest.main()
