"""Typed protobuf status validity; synthetic fixtures only."""
import unittest
from omarchy_mercedes.daemon import extract_status
from omarchy_mercedes.telemetry import decode_vehicle_attributes
from omarchy_mercedes.vendored import vehicle_events_pb2 as vep

class TelemetryValidityTest(unittest.TestCase):
    def test_unavailable_soc_is_not_reported_as_zero(self):
        for status in (1, 3, 4):
            with self.subTest(status=status):
                message=vep.VehicleStatusUpdate()
                message.soc.metadata.status=status
                message.soc.metadata.timestamp.seconds=1800000000
                result=extract_status(decode_vehicle_attributes(message.SerializeToString()),1800000000000)
                self.assertIsNone(result['soc_percent'])
                self.assertEqual(result['state'],'error')

    def test_valid_zero_soc_is_preserved(self):
        message=vep.VehicleStatusUpdate()
        message.soc.metadata.timestamp.seconds=1800000000
        result=extract_status(decode_vehicle_attributes(message.SerializeToString()),1800000000000)
        self.assertEqual(result['soc_percent'],0)
        self.assertEqual(result['state'],'ok')
