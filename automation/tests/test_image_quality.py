import unittest

from soloist_agent.image_quality import OcrWord, overlay_reason


class ImageQualityTests(unittest.TestCase):
    def test_known_shop_watermark_is_rejected(self) -> None:
        words = [
            OcrWord(1, 1, 1, 620, 833, 153, 39, 91, "线"),
            OcrWord(1, 1, 1, 704, 833, 69, 39, 95, "商店"),
        ]
        self.assertEqual(overlay_reason(words, 1280, 1707), "watermark:线商店")

    def test_large_advertising_title_at_top_is_rejected(self) -> None:
        words = [
            OcrWord(1, 1, 1, 145, 22, 182, 37, 80, "YDYJ"),
            OcrWord(1, 1, 1, 352, 21, 95, 38, 96, "RO"),
        ]
        self.assertTrue(overlay_reason(words, 580, 580))

    def test_tiny_product_label_is_allowed(self) -> None:
        words = [OcrWord(1, 1, 1, 470, 800, 45, 12, 90, "RICK")]
        self.assertEqual(overlay_reason(words, 1280, 1707), "")


if __name__ == "__main__":
    unittest.main()
