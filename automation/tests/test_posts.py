from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from soloist_agent.models import NormalizedProduct, PriceResult
from soloist_agent.posts import render_post


class PostTests(unittest.TestCase):
    def test_post_uses_store_template_and_telegram_html(self) -> None:
        product = NormalizedProduct(
            accepted=True,
            title="Футболка If Six Was Nine",
            brand="If Six Was Nine",
            category="tshirt",
            sizes="S-L",
            super_heavy=False,
        )
        price = PriceResult(2990, 5990, 50, 550, 1000, 1200, 2750)
        post = render_post(product, price)
        self.assertIn("Цена: <b>2990₽</b> <s>5990₽</s>", post)
        self.assertIn("Размеры: S-L\n\nЦена:", post)
        self.assertIn('<b><a href="https://t.me/soloist_store/392">УСЛОВИЯ ЗАКАЗА</a>', post)
        self.assertIn('<b>По заказу писать <a href="https://t.me/USERSOLOIST">MANAGER</a></b>', post)
        self.assertIn("НАЛИЧИЕ", post)
        self.assertIn("#Футболка", post)
        self.assertIn("#IfSixWasNine", post)
        self.assertLess(len(post), 1024)

    def test_brand_hashtag_excludes_archive_and_type(self) -> None:
        product = NormalizedProduct(
            accepted=True,
            title="Куртка ENFANTS RICHES DEPRIMES ARCHIVE",
            brand="ENFANTS RICHES DEPRIMES ARCHIVE TYPE",
            category="jacket",
            sizes="S-XXL",
            super_heavy=False,
        )
        price = PriceResult(8490, 11990, 29, 0, 0, 8990, 8490)
        post = render_post(product, price)
        self.assertIn("#ENFANTSRICHESDEPRIMES", post)
        self.assertNotIn("#ENFANTSRICHESDEPRIMESARCHIVE", post)
        self.assertNotIn("TYPE", post.splitlines()[-1])

    def test_catalog_hashtags_use_exact_type_and_brand_without_model(self) -> None:
        product = NormalizedProduct(
            accepted=True,
            title="Футболка Grailz project no pound kg",
            brand="Grailz project no pound kg",
            category="tshirt",
            sizes="S-XXL",
            super_heavy=False,
        )
        price = PriceResult(2300, 4990, 54, 0, 0, 2500, 2300)
        post = render_post(product, price)
        self.assertTrue(post.endswith("#Футболка #GRAILZPROJECT"))
        self.assertNotIn("nopoundkg", post.lower())

    def test_title_type_overrides_generic_other_hashtag(self) -> None:
        product = NormalizedProduct(
            accepted=True,
            title="Кепка Chrome Hearts из кожи",
            brand="Chrome Hearts",
            category="other",
            sizes="S-XXL",
            super_heavy=False,
        )
        price = PriceResult(3090, 5990, 48, 0, 0, 3290, 3090)
        post = render_post(product, price)
        self.assertTrue(post.endswith("#Кепка #ChromeHearts"))
        self.assertNotIn("#Одежда", post)

    def test_cyrillic_words_never_enter_brand_hashtag(self) -> None:
        price = PriceResult(3490, 6990, 50, 0, 0, 3790, 3490)
        bag = NormalizedProduct(
            accepted=True,
            title="Сумка YUEN из кожи",
            brand="YUEN из кожи",
            category="other",
            sizes="S-XXL",
            super_heavy=False,
        )
        hoodie = NormalizedProduct(
            accepted=True,
            title="Худи Opium laser на молнии",
            brand="Opium laser на молнии",
            category="sweater",
            sizes="S-XXL",
            super_heavy=False,
        )
        jeans = NormalizedProduct(
            accepted=True,
            title="Джинсы No faith studios Cargo",
            brand="No faith studios Cargo",
            category="jeans",
            sizes="S-XXL",
            super_heavy=False,
        )

        bag_post = render_post(bag, price)
        hoodie_post = render_post(hoodie, price)
        jeans_post = render_post(jeans, price)

        self.assertTrue(bag_post.endswith("#Сумка #YUEN"))
        self.assertTrue(hoodie_post.endswith("#Худи #OPIUM"))
        self.assertTrue(jeans_post.endswith("#Джинсы #NoFaithStudios"))
        self.assertNotIn("изкожи", bag_post.lower())
        self.assertNotIn("намолнии", hoodie_post.lower())


if __name__ == "__main__":
    unittest.main()
