"""Provenance is bounded and cannot change device commands."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'pixora_thermostat_controller'))
from insight_origin import OriginReporter
from ha import HomeAssistant


class Producers(unittest.IsolatedAsyncioTestCase):
    def test_packaged_reporters_match_shared_source(self):
        source = (ROOT/'tools/insight_origin.py').read_bytes()
        for app in ('pixora_thermostat_controller','pixora_led_displays'):
            self.assertEqual((ROOT/app/'insight_origin.py').read_bytes(), source)

    async def test_queue_is_bounded_and_failed_report_not_retried(self):
        sender = AsyncMock(side_effect=ValueError('unavailable'))
        reporter = OriginReporter(sender, 'Test app')
        reporter.emit(['light.kitchen'], 'Requested light action', context='01EXACTCOMMANDCONTEXT000001')
        await asyncio.sleep(.03)
        self.assertEqual(sender.await_count, 1)
        await asyncio.sleep(.03)
        self.assertEqual(sender.await_count, 1)
        await reporter.close()
        blocked = OriginReporter(AsyncMock(), 'Test app')
        for _ in range(34):blocked.emit([], 'Operation', operation='test.action')
        self.assertEqual(blocked.queue.qsize(), 32)
        await blocked.close()

    async def test_reporting_logger_failure_and_late_emit_cannot_escape(self):
        reporter = OriginReporter(AsyncMock(side_effect=RuntimeError('offline')), 'Test app')
        with patch('insight_origin.logging.getLogger', side_effect=RuntimeError('logger unavailable')):
            reporter.emit([], 'Action', operation='test.action')
            await asyncio.sleep(.02)
            self.assertFalse(reporter.task.done())
        await reporter.close()
        count = reporter.queue.qsize()
        reporter.emit([], 'Late action', operation='test.action')
        self.assertEqual(reporter.queue.qsize(), count)

    async def test_thermostat_uses_command_context_and_exact_reason(self):
        ha = HomeAssistant(None, 'test-token')
        ha.connected = True
        sent, reports = [], []
        async def send(message):
            sent.append(message)
            ha.pending[message['id']].set_result({'context': {'id': '01EXACTCOMMANDCONTEXT000001'}})
        ha.socket = type('Socket', (), {'send_json': staticmethod(send)})()
        async def record(report):reports.append(report)
        ha.origin = OriginReporter(record, 'Pixora Thermostat Controller')
        await ha.call_with_origin('climate.set_temperature', {'entity_id':'climate.hall', 'temperature':67}, 'Schedule Morning — Heat 67 F')
        await asyncio.sleep(.02)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['service_data']['temperature'], 67)
        self.assertEqual(reports[0]['action_context'], '01EXACTCOMMANDCONTEXT000001')
        self.assertIn('Morning', reports[0]['reason'])
        self.assertNotIn('temperature', reports[0])
        await ha.origin.close()

    async def test_disconnected_thermostat_does_not_send_or_log_a_command(self):
        ha = HomeAssistant(None, 'test-token')
        with self.assertRaises(ValueError):await ha.call('climate.turn_off', {'entity_id':'climate.hall'})
        self.assertTrue(ha.origin.queue.empty())

    async def test_unexpected_thermostat_reporter_failure_does_not_fail_action(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        ha = HomeAssistant(None, 'test-token');ha.connected = True
        async def send(message):ha.pending[message['id']].set_result({'context':{'id':'01EXACTCOMMANDCONTEXT000001'}})
        ha.socket = SimpleNamespace(send_json=send)
        ha.origin = SimpleNamespace(emit=Mock(side_effect=RuntimeError('reporter failed')))
        await ha.call_with_origin('climate.turn_off', {'entity_id':'climate.hall'}, 'Outdoor protection')
        self.assertEqual(ha.origin.emit.call_count,1)
        self.assertFalse(ha.pending)

    async def test_thermostat_socket_failure_is_controlled_and_not_retried(self):
        from aiohttp import ClientError
        ha = HomeAssistant(None, 'test-token');ha.connected = True
        ha.socket = type('Socket', (), {'send_json': AsyncMock(side_effect=ClientError('closed'))})()
        with self.assertRaises(ValueError):await ha.call('climate.turn_off', {'entity_id':'climate.hall'})
        self.assertEqual(ha.socket.send_json.await_count, 1)
        self.assertFalse(ha.pending)
        self.assertTrue(ha.origin.queue.empty())


if __name__ == '__main__':unittest.main()
