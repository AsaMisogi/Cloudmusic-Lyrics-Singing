import tempfile
import unittest
from pathlib import Path
from utatomo.language import Annotator, hiragana, to_ipa


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.annotator = Annotator(Path(cls.directory.name))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_contextual_reading_and_hiragana(self):
        words = self.annotator.annotate("朝の光を追いかけて")
        self.assertEqual(
            next(word["reading"] for word in words if word["text"] == "光"), "ひかり"
        )
        self.assertEqual(hiragana("ヒカリ"), "ひかり")

    def test_english_spaces_and_contractions(self):
        text = "I'll keep the light in your heart."
        tokens = self.annotator.annotate(text)
        self.assertEqual("".join(token["text"] for token in tokens), text)
        self.assertTrue(
            next(token["reading"] for token in tokens if token["text"] == "light")
        )

    def test_mixed_script_preserves_original(self):
        text = "君と sing again!"
        self.assertEqual(
            "".join(token["text"] for token in self.annotator.annotate(text)), text
        )

    def test_manual_override_and_revert(self):
        self.annotator.correct("明日", "あす")
        self.assertEqual(self.annotator.annotate("明日")[0]["reading"], "あす")
        self.annotator.correct("明日", "")
        self.assertNotIn("明日", self.annotator.overrides)

    def test_ipa_schwa_and_stress(self):
        self.assertEqual(to_ipa(["L", "AY1", "T"]), "ˈlaɪt")
        self.assertEqual(to_ipa(["AH0"]), "ə")


if __name__ == "__main__":
    unittest.main()
