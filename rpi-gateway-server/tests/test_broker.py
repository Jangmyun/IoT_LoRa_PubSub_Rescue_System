import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY_DIR = ROOT / "gateway"
sys.path.insert(0, str(GATEWAY_DIR))

from broker import Broker  # noqa: E402
from lib.packet import LoRaPublish, Topic  # noqa: E402


class BrokerTests(unittest.TestCase):
    def test_suppresses_immediate_duplicate_packet(self):
        async def scenario():
            broker = Broker()
            forwarded = []

            async def callback(pkt):
                forwarded.append(pkt.header.msg_id)

            broker.subscribe_all(callback)
            packet = LoRaPublish.build(1, 7, Topic.SENSOR_RAW, bytes([82, 98]))

            await broker.dispatch(packet)
            await broker.dispatch(packet)

            return forwarded

        self.assertEqual(asyncio.run(scenario()), [7])

    def test_allows_msg_id_after_short_history_wraps(self):
        async def scenario():
            broker = Broker()
            forwarded = []

            async def callback(pkt):
                forwarded.append(pkt.header.msg_id)

            broker.subscribe_all(callback)
            for msg_id in range(65):
                await broker.dispatch(
                    LoRaPublish.build(1, msg_id % 256, Topic.SENSOR_RAW, bytes([82, 98]))
                )
            await broker.dispatch(
                LoRaPublish.build(1, 0, Topic.SENSOR_RAW, bytes([83, 99]))
            )

            return forwarded

        forwarded = asyncio.run(scenario())
        self.assertEqual(len(forwarded), 66)
        self.assertEqual(forwarded[0], 0)
        self.assertEqual(forwarded[-1], 0)


if __name__ == "__main__":
    unittest.main()
