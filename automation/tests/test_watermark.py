import io
import unittest

from PIL import Image, ImageChops, ImageStat

from soloist_agent.watermark import WatermarkError, apply_center_watermark


class WatermarkTests(unittest.TestCase):
    def test_watermark_is_centered_and_preserves_dimensions(self) -> None:
        source = Image.new("RGB", (900, 1200), (35, 35, 35))
        payload = io.BytesIO()
        source.save(payload, format="PNG")

        processed = apply_center_watermark(payload.getvalue(), opacity=150)
        result = Image.open(io.BytesIO(processed.body)).convert("RGB")

        self.assertEqual(result.size, source.size)
        self.assertEqual(processed.content_type, "image/jpeg")
        difference = ImageChops.difference(source, result)
        center = difference.crop((180, 420, 720, 780))
        top = difference.crop((180, 40, 720, 250))
        self.assertIsNotNone(center.getbbox())
        center_mean = ImageStat.Stat(center.convert("L")).mean[0]
        top_mean = ImageStat.Stat(top.convert("L")).mean[0]
        self.assertGreater(center_mean, top_mean + 2)

    def test_transparent_image_remains_png(self) -> None:
        source = Image.new("RGBA", (400, 400), (20, 20, 20, 180))
        payload = io.BytesIO()
        source.save(payload, format="PNG")

        processed = apply_center_watermark(payload.getvalue())

        self.assertEqual(processed.content_type, "image/png")
        self.assertEqual(processed.extension, ".png")

    def test_invalid_image_is_rejected(self) -> None:
        with self.assertRaises(WatermarkError):
            apply_center_watermark(b"not-an-image")


if __name__ == "__main__":
    unittest.main()
