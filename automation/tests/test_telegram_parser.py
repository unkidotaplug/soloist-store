import unittest

from soloist_agent.sources.telegram_channel import parse_channel_html


SAMPLE = """
<div class="tgme_widget_message" data-post="destiny_place/16218">
  <a class="tgme_widget_message_date" href="https://t.me/destiny_place/16218"></a>
  <a class="tgme_widget_message_photo_wrap" style="background-image:url('https://cdn.example/a.jpg')"></a>
  <a class="tgme_widget_message_photo_wrap" style="background-image:url('https://cdn.example/b.jpg')"></a>
  <div class="tgme_widget_message_text">
    💵 IF SIX WAS NINE T-SHIRT<br>
    💯 ВСЕ БИРКИ СООТВЕТСТВУЮТ ОРИГИНАЛУ<br>
    🎼 Размеры: S-L<br>
    🧛 Цена: 6 120₽ 3 490₽<br>
    #ФУТБОЛКА
  </div>
</div>
"""

IKARU_SAMPLE = """
<div class="tgme_widget_message" data-post="ikarushop/4993">
  <a class="tgme_widget_message_date" href="https://t.me/ikarushop/4993"></a>
  <a class="tgme_widget_message_photo_wrap" style="background-image:url('https://cdn.example/1.jpg')"></a>
  <div class="tgme_widget_message_text">
    PALY HOLLYWOOD Synan on hoodie<br>
    Size: S M L XL<br>
    4.900₽<br>
    #replique<br>
    Купить - @SWAGDRIPCHIK
  </div>
</div>
"""


class TelegramParserTests(unittest.TestCase):
    def test_parses_discounted_price_sizes_and_album(self) -> None:
        products = parse_channel_html(SAMPLE, "destiny_place")
        self.assertEqual(len(products), 1)
        product = products[0]
        self.assertEqual(product.external_id, "destiny_place:16218")
        self.assertEqual(str(product.price), "3490")
        self.assertEqual(product.sizes, "S-L")
        self.assertEqual(product.title, "IF SIX WAS NINE T-SHIRT")
        self.assertEqual(len(product.media), 2)

    def test_parses_ikarushop_price_without_price_label(self) -> None:
        products = parse_channel_html(IKARU_SAMPLE, "ikarushop")
        self.assertEqual(len(products), 1)
        product = products[0]
        self.assertEqual(product.external_id, "ikarushop:4993")
        self.assertEqual(str(product.price), "4900")
        self.assertEqual(product.sizes, "S M L XL")
        self.assertEqual(product.title, "PALY HOLLYWOOD Synan on hoodie")
        self.assertEqual(product.raw["channel"], "ikarushop")


if __name__ == "__main__":
    unittest.main()
