"""在 Qt 的 JS 引擎里用确定的时间验证真实前端时钟。"""
import unittest
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine


class ClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.engine = QJSEngine()
        source = (Path(__file__).resolve().parents[1] / "web/playback-clock.js").read_text(encoding="utf-8")
        result = self.engine.evaluate(source + "\nvar clock = new PlaybackClock();")
        self.assertFalse(result.isError(), result.toString())

    def js(self, code):
        value = self.engine.evaluate(code)
        self.assertFalse(value.isError(), value.toString())
        return value.toVariant()

    def test_quantized_samples_do_not_reverse_or_jump(self):
        result = self.js("""
            var positions = [], maxStep = 0, minStep = 100;
            for (var now=0; now<=5000; now+=10) {
              if (now % 100 === 0) clock.update({position: 2000 + Math.floor(now/500)*500, playing:true}, now);
              var p = clock.read(now);
              if (positions.length) { var delta=p-positions[positions.length-1]; maxStep=Math.max(maxStep,delta); minStep=Math.min(minStep,delta); }
              positions.push(p);
            }
            [minStep, maxStep, positions[positions.length-1]];
        """)
        self.assertGreaterEqual(result[0], 0)
        self.assertLess(result[1], 14)
        self.assertAlmostEqual(result[2], 7000, delta=100)

    def test_stalled_source_freezes_without_rolling_back(self):
        result = self.js("""
            clock.update({position:1000,playing:true},0);
            for(var t=100;t<=8000;t+=100) clock.update({position:1000,playing:true},t);
            [clock.read(8000),clock.read(9000)];
        """)
        self.assertEqual(result, [2500, 2500])

    def test_backward_loop_and_external_seek(self):
        self.js("clock.update({position:5000,playing:true},0); clock.update({position:4200,playing:true},100);")
        self.assertEqual(self.js("clock.read(100)"), 4200)
        self.js("clock.update({position:22000,playing:true},200);")
        self.assertEqual(self.js("clock.read(200)"), 22000)

    def test_pause_seek_rate_and_track_change(self):
        self.js("clock.update({position:1000,playing:true},0); clock.update({position:1100,playing:false},100);")
        self.assertEqual(self.js("clock.read(2000)"), 1100)
        self.js("clock.update({position:1110,playing:false},2100);")
        self.assertEqual(self.js("clock.read(2200)"), 1110)
        self.js("clock.update({position:1110,playing:true,rate:.5},2300);")
        self.assertEqual(self.js("clock.read(2500)"), 1210)
        self.js("clock.update({identity:'new',position:0,playing:true},2500);")
        self.assertEqual(self.js("clock.read(2500)"), 0)

    def test_quantized_pause_does_not_change_line_on_next_snapshot(self):
        self.js("clock.update({position:1000,playing:true},0); clock.update({position:1000,playing:false},200);")
        self.assertEqual(self.js("clock.read(200)"), 1200)
        self.js("clock.update({position:1000,playing:false},400);")
        self.assertEqual(self.js("clock.read(400)"), 1200)
