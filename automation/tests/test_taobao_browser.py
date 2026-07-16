from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from soloist_agent.config import Settings
from soloist_agent.sources.taobao_browser import TaobaoBrowserSource, _group_same_models


class TaobaoBrowserMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        settings = Settings(
            project_dir=base,
            data_dir=base,
            database_path=base / "db.sqlite3",
            taobao_browser_profile=base / "profile",
        )
        self.source = TaobaoBrowserSource(settings)

    def test_browser_row_maps_to_cny_candidate(self) -> None:
        candidate = self.source._candidate(
            {
                "external_id": "123456",
                "source_url": "https://item.taobao.com/item.htm?id=123456",
                "title": "Rick Owens 复古鞋",
                "price": "128.50",
                "media": ["//img.alicdn.com/cover.jpg", "//img.alicdn.com/cover.jpg"],
            },
            "Rick Owens",
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.currency, "CNY")
        self.assertEqual(str(candidate.price), "128.50")
        self.assertEqual(candidate.sizes, "S-XXL")
        self.assertEqual(candidate.media, ["https://img.alicdn.com/cover.jpg"])
        self.assertEqual(candidate.raw["search_keyword"], "Rick Owens")

    def test_invalid_row_is_ignored(self) -> None:
        self.assertIsNone(
            self.source._candidate(
                {"external_id": "123", "source_url": "https://item.taobao.com", "price": ""},
                "Rick Owens",
            )
        )

    def test_digital_reference_pack_is_ignored(self) -> None:
        self.assertIsNone(
            self.source._candidate(
                {
                    "external_id": "123",
                    "source_url": "https://item.taobao.com/item.htm?id=123",
                    "title": "rick owens 高清参考素材图集",
                    "price": "19",
                    "media": ["https://img.alicdn.com/cover.jpg"],
                },
                "Rick Owens",
            )
        )

    def test_same_model_listings_are_grouped_and_sorted_by_price(self) -> None:
        expensive = self.source._candidate(
            {
                "external_id": "222",
                "source_url": "https://item.taobao.com/item.htm?id=222",
                "title": "Rick Owens 复古高帮鞋 男女同款",
                "price": "749",
                "media": [],
            },
            "Rick Owens",
        )
        cheaper = self.source._candidate(
            {
                "external_id": "111",
                "source_url": "https://item.taobao.com/item.htm?id=111",
                "title": "Rick Owens 复古高帮鞋",
                "price": "520",
                "media": [],
            },
            "Rick Owens",
        )
        other_model = self.source._candidate(
            {
                "external_id": "333",
                "source_url": "https://item.taobao.com/item.htm?id=333",
                "title": "Rick Owens LUXOR 低帮鞋",
                "price": "480",
                "media": [],
            },
            "Rick Owens",
        )
        assert expensive and cheaper and other_model
        groups = _group_same_models([expensive, cheaper, other_model])
        self.assertEqual(len(groups), 2)
        duplicate_group = next(group for group in groups if len(group) == 2)
        self.assertEqual([item.external_id for item in duplicate_group], ["111", "222"])

    def test_detail_gallery_removes_resized_duplicates_and_platform_assets(self) -> None:
        media = self.source._detail_media(
            [
                "https://img.alicdn.com/x/O1CN01abc_!!2734996270.jpg_q50.jpg_.webp",
                "https://gw.alicdn.com/y/O1CN01abc_!!2734996270.jpg_.webp",
                "https://img.alicdn.com/x/O1CN02def_!!2734996270.jpg_.webp",
                "https://img.alicdn.com/x/O1CN03ui_!!6000000003931.png",
            ],
            [],
        )
        self.assertEqual(len(media), 2)
        self.assertIn("O1CN01abc", media[0])

    def test_visual_model_features_group_cheaper_differently_named_listing(self) -> None:
        original = self.source._candidate(
            {
                "external_id": "700",
                "source_url": "https://item.taobao.com/item.htm?id=700",
                "title": "RICK OCEAN RO dunk大钩子牛皮vibe高帮鞋",
                "price": "700",
                "media": [],
            },
            "Rick Owens",
        )
        cheaper = self.source._candidate(
            {
                "external_id": "107",
                "source_url": "https://item.taobao.com/item.htm?id=107",
                "title": "大钩子RO鞋子倒三角厚底增高高帮鞋",
                "price": "107",
                "media": [],
            },
            "Rick Owens",
        )
        assert original and cheaper
        groups = _group_same_models([original, cheaper])
        self.assertEqual(len(groups), 1)
        self.assertEqual([item.external_id for item in groups[0]], ["107", "700"])


if __name__ == "__main__":
    unittest.main()
