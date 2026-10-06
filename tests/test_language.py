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

    def test_romaji_combinations_and_long_vowels(self):
        for kana, expected in (("きっと", "kitto"), ("まっちゃ", "matcha"),
                               ("キャット", "kyatto"), ("がっこう", "gakkou"),
                               ("コーヒー", "koohii")):
            with self.subTest(kana=kana):
                self.assertEqual(self.annotator.romanize(kana), expected)

    def test_romaji_uses_resolved_song_reading(self):
        line = {"start": 0, "text": "宇宙を抱いて", "pronunciation": "so ra wo i da i te"}
        self.annotator.enrich([line], "roman-song")
        token = line["tokens"][0]
        self.assertEqual(token["reading"], "そら")
        self.assertEqual(token["romaji"], "sora")
        self.assertNotIn("romaji", self.annotator.annotate(line["text"])[0])

    def test_romaji_follows_correction_and_revert(self):
        line = {"start": 0, "text": "明日", "pronunciation": "a su"}
        self.annotator.enrich([line], "roman-correction")
        token = line["tokens"][0]
        args = ("roman-correction", token["lineKey"], token["tokenStart"])
        self.annotator.correct("明日", "みらい", *args)
        self.annotator.enrich([line], "roman-correction")
        self.assertEqual(line["tokens"][0]["romaji"], "mirai")
        self.assertEqual(line["tokens"][0]["reading"], "みらい")
        self.annotator.correct("明日", "", *args)
        self.annotator.enrich([line], "roman-correction")
        self.assertEqual(line["tokens"][0]["romaji"], "asu")

    def test_romaji_kana_only_english_and_punctuation(self):
        line = {"start": 0, "text": "コーヒー sing!"}
        self.annotator.enrich([line])
        self.assertEqual("".join(t["text"] for t in line["tokens"]), line["text"])
        coffee = next(t for t in line["tokens"] if t["text"] == "コーヒー")
        self.assertEqual(coffee["reading"], "")
        self.assertEqual(coffee["romaji"], "koohii")
        for token in line["tokens"]:
            if token["language"] != "ja" or not token["text"].strip(" !"):
                self.assertEqual(token["romaji"], "")
        english = next(t for t in line["tokens"] if t["text"] == "sing")
        self.assertEqual(english["reading"], self.annotator.english_token("sing")["reading"])

    def test_romaji_particles_use_contextual_pronunciation(self):
        line = {"start": 0, "text": "君は明日へ光を追いかけて"}
        self.annotator.enrich([line])
        particles = {t["text"]: t for t in line["tokens"] if t["pos"] == "助詞"}
        for text, expected in (("は", "wa"), ("へ", "e"), ("を", "o")):
            self.assertEqual(particles[text]["romaji"], expected)
            self.assertEqual(particles[text]["reading"], "")


if __name__ == "__main__":
    unittest.main()
