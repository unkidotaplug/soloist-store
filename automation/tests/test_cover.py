from io import BytesIO
import unittest

from PIL import Image

from soloist_agent.cover import CANVAS_SIZE, create_product_cover


class CoverTests(unittest.TestCase):
    def test_cover_is_telegram_ready_four_by_five_jpeg(self) -> None:
        source = Image.new("RGB", (640, 900), "#70665d")
        payload = BytesIO()
        source.save(payload, format="JPEG")

        cover = create_product_cover(payload.getvalue(), "Куртка Rick Owens Archive")

        with Image.open(BytesIO(cover)) as rendered:
            self.assertEqual(rendered.format, "JPEG")
            self.assertEqual(rendered.size, CANVAS_SIZE)
        self.assertLess(len(cover), 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
