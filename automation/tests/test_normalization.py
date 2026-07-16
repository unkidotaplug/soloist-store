from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from soloist_agent.ai import ProductNormalizer
from soloist_agent.config import Settings
from soloist_agent.models import ProductCandidate


class NormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.normalizer = ProductNormalizer(
            Settings(project_dir=base, data_dir=base, database_path=base / "db.sqlite3")
        )

    def candidate(self, title: str, category: str, sizes: str) -> ProductCandidate:
        return ProductCandidate(
            source="telegram",
            external_id=title,
            source_url="",
            title=title,
            price=Decimal("5000"),
            currency="RUB",
            category=category,
            sizes=sizes,
        )

    def test_clothing_always_uses_s_to_xxl(self) -> None:
        product = self.normalizer.heuristic(
            self.candidate("ENFANTS RICHES DEPRIMES ARCHIVE JACKET", "jacket", "s-XL")
        )
        self.assertEqual(product.sizes, "S-XXL")
        self.assertEqual(product.brand, "ENFANTS RICHES DEPRIMES")

    def test_shoes_always_use_36_to_45(self) -> None:
        product = self.normalizer.heuristic(
            self.candidate("BALENCIAGA BULLDOZER BOOTS", "shoes", "39-44")
        )
        self.assertEqual(product.sizes, "36-45")

    def test_accessory_does_not_get_clothing_sizes(self) -> None:
        product = self.normalizer.heuristic(self.candidate("KMIRI TYPE CHAIN", "accessory", "1"))
        self.assertEqual(product.sizes, "Уточняйте у менеджера")
        self.assertEqual(product.brand, "KMIRI")

    def test_marketplace_uses_search_keyword_as_brand(self) -> None:
        candidate = ProductCandidate(
            source="taobao",
            external_id="123",
            source_url="https://item.taobao.com/item.htm?id=123",
            title="RO自主大钩子牛皮高帮鞋",
            price=Decimal("700"),
            currency="CNY",
            raw={"search_keyword": "Rick Owens"},
        )
        product = self.normalizer.heuristic(candidate)
        self.assertEqual(product.brand, "Rick Owens")
        self.assertEqual(product.title, "Обувь Rick Owens")
        self.assertEqual(product.category, "shoes")
        self.assertEqual(product.sizes, "36-45")

    def test_erd_alias_expands_to_full_brand(self) -> None:
        candidate = ProductCandidate(
            source="telegram",
            external_id="ikarushop:4982",
            source_url="https://t.me/ikarushop/4982",
            title="ERD Dorothy Dunked Hoodie",
            price=Decimal("5700"),
            currency="RUB",
        )

        product = self.normalizer.heuristic(candidate)

        self.assertEqual(product.brand, "ENFANTS RICHES DEPRIMES")
        self.assertTrue(product.title.startswith("Худи "))

    def test_grailz_model_is_not_part_of_brand(self) -> None:
        product = self.normalizer.heuristic(
            self.candidate("Grailz project no pound kg T-shirt", "tshirt", "S-XL")
        )
        self.assertEqual(product.brand, "Grailz project")
        self.assertEqual(product.title, "Футболка Grailz project no pound kg")

    def test_trailing_long_sets_longsleeve_category(self) -> None:
        product = self.normalizer.heuristic(
            self.candidate("Ann Demeulemeester long", "other", "S-XL")
        )
        self.assertEqual(product.category, "longsleeve")
        self.assertEqual(product.title, "Лонгслив Ann Demeulemeester")


if __name__ == "__main__":
    unittest.main()
