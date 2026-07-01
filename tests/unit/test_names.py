import unittest

from football_prediction.providers.names import name_key


class NameKeyTests(unittest.TestCase):
    def test_cjk_names_are_preserved_and_distinct(self):
        names = ["英格兰", "刚果金", "比利时", "塞内加尔", "美国", "波黑"]
        keys = [name_key(name) for name in names]
        self.assertEqual(keys, names)
        self.assertEqual(len(set(keys)), len(names))

    def test_latin_diacritics_are_stripped(self):
        self.assertEqual(name_key("São Paulo"), "saopaulo")
        self.assertEqual(name_key("Müller"), "muller")

    def test_club_suffixes_are_dropped(self):
        self.assertEqual(name_key("Arsenal FC"), name_key("Arsenal"))


if __name__ == "__main__":
    unittest.main()
