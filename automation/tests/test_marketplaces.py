from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from soloist_agent.config import Settings
from soloist_agent.sources.pdd import PddSource
from soloist_agent.sources.taobao import TaobaoSource


class MarketplaceMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.settings = Settings(project_dir=base, data_dir=base, database_path=base / "db.sqlite3")

    def test_taobao_mapping_uses_cny_and_gallery(self) -> None:
        candidate = TaobaoSource(self.settings)._candidate(
            {
                "num_iid": 123,
                "title": "<span>Rick Owens</span> 鞋",
                "zk_final_price": "88.90",
                "pict_url": "//img.example/cover.jpg",
                "small_images": {"string": ["//img.example/2.jpg"]},
                "item_url": "//item.taobao.com/item.htm?id=123",
                "category_name": "鞋",
            }
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(str(candidate.price), "88.90")
        self.assertEqual(candidate.currency, "CNY")
        self.assertEqual(len(candidate.media), 2)
        self.assertTrue(candidate.source_url.startswith("https:"))

    def test_pdd_mapping_converts_fen_to_yuan(self) -> None:
        candidate = PddSource(self.settings)._candidate(
            {
                "goods_id": 456,
                "goods_name": "Balenciaga jacket",
                "min_group_price": "34900",
                "goods_image_url": "https://img.example/cover.jpg",
                "goods_gallery_urls": ["https://img.example/2.jpg"],
            }
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(str(candidate.price), "349")
        self.assertEqual(candidate.currency, "CNY")
        self.assertIn("goods_id=456", candidate.source_url)


if __name__ == "__main__":
    unittest.main()
