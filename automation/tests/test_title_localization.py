import unittest

from soloist_agent.ai import localize_product_title


class TitleLocalizationTests(unittest.TestCase):
    def test_jacket_moves_to_russian_prefix(self) -> None:
        self.assertEqual(
            localize_product_title("ENFANTS RICHES DEPRIMES ARCHIVE JACKET", "jacket"),
            "Куртка ENFANTS RICHES DEPRIMES ARCHIVE",
        )

    def test_tshirt_moves_to_russian_prefix(self) -> None:
        self.assertEqual(
            localize_product_title("IF SIX WAS NINE T-SHIRT", "tshirt"),
            "Футболка IF SIX WAS NINE",
        )

    def test_jeans_moves_to_russian_prefix(self) -> None:
        self.assertEqual(
            localize_product_title("ERD DOUBLE-KNEE WORK JEANS", "jeans"),
            "Джинсы ERD DOUBLE-KNEE WORK",
        )

    def test_cap_moves_to_russian_prefix(self) -> None:
        self.assertEqual(
            localize_product_title("CHROME HEARTS LEATHER CAP", "other"),
            "Кепка CHROME HEARTS из кожи",
        )

    def test_descriptor_after_existing_russian_type_is_localized(self) -> None:
        self.assertEqual(
            localize_product_title("Джинсы ANN DEMEULEMEESTER CLAIRE 5 POCKETS", "jeans"),
            "Джинсы ANN DEMEULEMEESTER CLAIRE с 5 карманами",
        )

    def test_trailing_long_is_longsleeve(self) -> None:
        self.assertEqual(
            localize_product_title("Ann Demeulemeester long", "longsleeve"),
            "Лонгслив Ann Demeulemeester",
        )

    def test_other_common_types_are_localized(self) -> None:
        self.assertEqual(
            localize_product_title("Maison Margiela Distressed Cardigan", "sweater"),
            "Кардиган Maison Margiela с потёртостями",
        )
        self.assertEqual(
            localize_product_title("Martine Rose polo", "other"),
            "Поло Martine Rose",
        )

    def test_existing_russian_title_is_unchanged(self) -> None:
        self.assertEqual(localize_product_title("Куртка Undercover", "jacket"), "Куртка Undercover")


if __name__ == "__main__":
    unittest.main()
