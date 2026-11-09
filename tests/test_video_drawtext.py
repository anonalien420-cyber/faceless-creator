import tempfile
import unittest

from src.video import _drawtext_path, _write_drawtext_file


class DrawtextFileTests(unittest.TestCase):
    def test_textfile_preserves_ffmpeg_special_characters(self):
        text = """Here's 100%: history, "quotes", \\slashes\\ and [brackets]"""
        with tempfile.TemporaryDirectory() as directory:
            path = _write_drawtext_file(directory, "fixture", text)
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), text)

    def test_generated_textfile_path_is_filter_escaped(self):
        self.assertEqual(_drawtext_path(r"C:\\temp\\file.txt"),
                         r"C\\:\\\\temp\\\\file.txt")
        self.assertEqual(_drawtext_path("/tmp/a:b.txt"), "/tmp/a\\:b.txt")


if __name__ == "__main__":
    unittest.main()
