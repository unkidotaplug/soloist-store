from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from soloist_agent.config import Settings
from soloist_agent.models import ProductCandidate
from soloist_agent.pricing import calculate_price, retail_round_up


class PricingTests(unittest.TestCase):
    def settings(self) -> Settings:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        return Settings(project_dir=base, data_dir=base, database_path=base / "db.sqlite3")

    def test_retail_rounding(self) -> None:
        self.assertEqual(retail_round_up(2342), 2490)
        self.assertEqual(retail_round_up(2490), 2490)
        self.assertEqual(retail_round_up(2491), 2990)

    def test_marketplace_tshirt_formula(self) -> None:
        candidate = ProductCandidate(
            source="taobao",
            external_id="shirt-1",
            source_url="",
            title="T-shirt",
            price=Decimal("55"),
            currency="CNY",
            category="tshirt",
        )
        result = calculate_price(candidate, self.settings())
        self.assertEqual(result.procurement_rub, 822)
        self.assertIn(result.delivery, range(500, 601, 10))
        self.assertEqual(result.markup, 1000)
        self.assertEqual(result.sale_price, 2490)
        self.assertGreater(result.old_price, result.sale_price)
        self.assertGreaterEqual(result.discount_percent, 25)
        self.assertLessEqual(result.discount_percent, 70)

    def test_canonical_category_from_ai_is_preserved(self) -> None:
        candidate = ProductCandidate(
            source="taobao",
            external_id="shirt-ai",
            source_url="",
            title="商品",
            price=Decimal("55"),
            currency="CNY",
            category="tshirt",
        )
        result = calculate_price(candidate, self.settings())
        self.assertEqual(result.markup, 1000)
        self.assertIn(result.delivery, range(500, 601, 10))

    def test_competitor_is_500_cheaper_before_rounding(self) -> None:
        candidate = ProductCandidate(
            source="telegram",
            external_id="post-1",
            source_url="",
            title="Jeans",
            price=Decimal("5490"),
            currency="RUB",
            category="jeans",
        )
        result = calculate_price(candidate, self.settings())
        self.assertEqual(result.unrounded_total, 4990)
        self.assertEqual(result.sale_price, 4990)

    def test_low_competitor_price_uses_200_or_300_discount(self) -> None:
        candidate = ProductCandidate(
            source="telegram",
            external_id="destiny_place:16243",
            source_url="",
            title="CHROME HEARTS LEATHER CAP",
            price=Decimal("3290"),
            currency="RUB",
            category="other",
        )
        result = calculate_price(candidate, self.settings())
        self.assertIn(3290 - result.sale_price, {200, 300})
        self.assertEqual(result.sale_price, result.unrounded_total)
        self.assertEqual(result.sale_price, 3090)

    def test_asphyxia_price_is_1000_more_than_source(self) -> None:
        candidate = ProductCandidate(
            source="telegram",
            external_id="asphyxia_store:53",
            source_url="https://t.me/asphyxia_store/53",
            title="Джинсы ENFANTS RICHES DEPRIMES",
            price=Decimal("4490"),
            currency="RUB",
            category="jeans",
            raw={"channel": "@asphyxia_store"},
        )
        result = calculate_price(candidate, self.settings())
        self.assertEqual(result.procurement_rub, 4490)
        self.assertEqual(result.markup, 1000)
        self.assertEqual(result.unrounded_total, 5490)
        self.assertEqual(result.sale_price, 5490)

    def test_asphyxia_channel_can_be_detected_from_external_id(self) -> None:
        candidate = ProductCandidate(
            source="telegram",
            external_id="asphyxia_store:46",
            source_url="",
            title="Ботинки Balenciaga",
            price=Decimal("8990"),
            currency="RUB",
            category="shoes",
        )
        result = calculate_price(candidate, self.settings())
        self.assertEqual(result.sale_price, 9990)

    def test_random_values_are_stable_per_product(self) -> None:
        candidate = ProductCandidate(
            source="taobao",
            external_id="stable-id",
            source_url="",
            title="Футболка",
            price=Decimal("80"),
            currency="CNY",
        )
        first = calculate_price(candidate, self.settings())
        second = calculate_price(candidate, self.settings())
        self.assertEqual(first, second)

    def test_generated_discount_always_stays_in_requested_range(self) -> None:
        settings = self.settings()
        for index in range(100):
            candidate = ProductCandidate(
                source="telegram",
                external_id=f"discount-{index}",
                source_url="",
                title="Accessory",
                price=Decimal("990"),
                currency="RUB",
            )
            result = calculate_price(candidate, settings)
            self.assertGreaterEqual(result.discount_percent, 25)
            self.assertLessEqual(result.discount_percent, 70)


if __name__ == "__main__":
    unittest.main()
