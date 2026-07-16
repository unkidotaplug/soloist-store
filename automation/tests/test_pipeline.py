from decimal import Decimal
import unittest

from soloist_agent.models import ProductCandidate
from soloist_agent.pipeline import _round_robin


def candidate(channel: str, message_id: int) -> ProductCandidate:
    return ProductCandidate(
        source="telegram",
        external_id=f"{channel}:{message_id}",
        source_url=f"https://t.me/{channel}/{message_id}",
        title="Товар",
        price=Decimal("1000"),
        currency="RUB",
    )


class PipelineTests(unittest.TestCase):
    def test_sources_are_interleaved_so_one_channel_cannot_fill_the_queue(self) -> None:
        destiny = [candidate("destiny_place", 3), candidate("destiny_place", 2)]
        ikaru = [candidate("ikarushop", 9), candidate("ikarushop", 8)]

        result = _round_robin([destiny, [], ikaru])

        self.assertEqual(
            [item.external_id for item in result],
            ["destiny_place:3", "ikarushop:9", "destiny_place:2", "ikarushop:8"],
        )


if __name__ == "__main__":
    unittest.main()
