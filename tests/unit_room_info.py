from datetime import datetime
from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.error import URLError

from jarvis.assistant import room_info as room
from jarvis.assistant import jarvis_assistant as assistant

NOW = datetime.fromisoformat('2026-10-23T12:00:00-07:00')


def point(value, time='2026-10-23T11:50:00-07:00', run='one', source='capture'):
    return {'count': value, 'time': time, 'run_id': run, 'source': source}


def daily(points=None, latest=None):
    points = points if points is not None else [point(18)]
    return {'day': '2026-10-23', 'timezone': 'America/Los_Angeles',
            'observations': points, 'latest_observation': latest if latest is not None else (points[-1] if points else None), 'warnings': []}


class RoomInfoTests(unittest.TestCase):
    def answer(self, request, data):
        return room.answer(request, fetch=lambda path: data, now=NOW)

    def test_voice_questions_and_polite_variants(self):
        examples = {
            'current': ['How many people are in the room?', 'Hey Jarvis, please tell me how many students are there in the classroom right now.', "What's the current occupancy?"],
            'peak': ["What was today's highest occupancy?", 'What is the highest occupancy today?', 'Jarvis, could you tell me what was the peak occupancy today please?'],
            'busiest': ['When was the room busiest?', 'When was the classroom the busiest today?'],
            'last_capture': ['When was the last picture taken?', 'When did you last take a photo?'],
            'analyzed': ['How many pictures were analyzed today?', 'How many captures have you processed today?']}
        for expected, phrases in examples.items():
            for phrase in phrases:
                self.assertEqual(room.intent(phrase), expected, phrase)
        for phrase in ['take a picture', 'last song', 'how many people live in France',
                       'what was the highest occupancy yesterday', 'delete room data',
                       'play people are in the room', 'what was the highest occupancy tomorrow']:
            self.assertIsNone(room.intent(phrase), phrase)

    def test_current_count_zero_and_freshness(self):
        for value in (0, 1, 18):
            result = self.answer('current', daily([point(value)]))
            self.assertIn(room.people(value), result)
            self.assertIn('11:50 AM Pacific time', result)
            self.assertIn('not a live headcount', result)
            self.assertNotIn('older observation', result)
        result = self.answer('current', daily(latest=point(0, '2026-10-22T22:50:00-07:00')))
        self.assertIn('October 22, 2026', result)
        self.assertIn('older observation', result)

    def test_no_data_is_not_zero_and_invalid_counts_not_spoken(self):
        for request in ['current', 'peak', 'busiest']:
            result = self.answer(request, daily([]))
            self.assertIn('does not mean', result)
            self.assertNotIn('0 people', result)
        for value in [True, -1, 2.5, '12', None]:
            result = self.answer('current', daily(latest=point(value)))
            self.assertIn('cannot confirm', result)
        self.assertIn('cannot confirm', self.answer('current', daily(latest=point(5, '2026-10-23T13:00:00-07:00'))))
        self.assertIn('cannot confirm', self.answer('current', daily(latest=point(5, '2026-10-23T11:00:00'))))

    def test_peak_ties_and_today_boundary(self):
        points = [point(30, '2026-10-22T23:59:00-07:00'), point(22, '2026-10-23T10:10:00-07:00'),
                  point(22, '2026-10-23T11:20:00-07:00'), point(100, '2026-10-23T13:00:00-07:00')]
        for request in ['peak', 'busiest']:
            result = self.answer(request, daily(points))
            self.assertIn('22 people', result)
            self.assertIn('10:10 AM', result)
            self.assertIn('other saved observations', result)
            self.assertIn('saved observations only', result)
        data = daily([point(0)])
        self.assertIn('0 people', self.answer('peak', data))
        data['day'] = '2026-10-22'
        self.assertIn('cannot confirm', self.answer('peak', data))

    def test_pacific_day_uses_timezone_not_utc_date(self):
        data = daily([point(4, '2026-10-23T06:50:00+00:00')])
        data['day'] = '2026-10-22'
        result = room.answer('peak', fetch=lambda _: data, now=datetime.fromisoformat('2026-10-23T06:55:00+00:00'))
        self.assertIn('4 people', result)
        self.assertIn('11:50 PM Pacific time', result)

    def test_analysis_counts_all_completed_captures_not_events_or_duplicates(self):
        points = [point(3), point(3), point(0, run='two'), point(8, run='event', source='monitor event'), point(None, run='incomplete')]
        result = self.answer('analyzed', daily(points))
        self.assertIn('2 saved captures', result)
        self.assertIn('may be incomplete', result)
        self.assertIn('0 saved captures', self.answer('analyzed', daily([])))

    def test_capture_time_pending_and_unavailable(self):
        data = {'timezone': 'America/Los_Angeles', 'last_capture': '2026-10-23T11:55:00-07:00', 'analysis': 'processing'}
        self.assertIn('11:55 AM Pacific time', self.answer('last_capture', data))
        self.assertIn('still pending', self.answer('last_capture', data))
        data['state'] = 'unavailable'
        self.assertIn('cannot confirm', self.answer('last_capture', data))
        data.pop('state');data['last_capture'] = None
        self.assertIn('No saved picture', self.answer('last_capture', data))

    def test_warning_and_fetch_failures(self):
        data = daily();data['warnings'] = ['Partial history']
        self.assertIn('may be incomplete', self.answer('peak', data))
        for error in [room.RoomDataError('offline'), TimeoutError('slow')]:
            with patch.object(room, 'fetch_json', side_effect=error):
                self.assertIn('cannot confirm', room.answer('current', now=NOW))
        data['timezone'] = 'Invalid/Zone'
        self.assertIn('cannot confirm', self.answer('peak', data))

    def test_transport_bounds_json_and_timeout(self):
        for raw in [b'{"timezone":"UTC"}', b'[]', b'not JSON', b'x' * (room.MAX_BYTES + 1)]:
            opener = unittest.mock.Mock()
            opener.open.return_value = BytesIO(raw)
            with patch.object(room, 'build_opener', return_value=opener), patch.dict(room.os.environ, {'JARVIS_ROOM_API_URL': 'http://127.0.0.1:8000'}):
                if raw.startswith(b'{'):
                    self.assertEqual(room.fetch_json('/api/occupancy'), {'timezone': 'UTC'})
                else:
                    with self.assertRaises(room.RoomDataError):
                        room.fetch_json('/api/occupancy')
                opener.open.assert_called_once_with('http://127.0.0.1:8000/api/occupancy', timeout=3)
        with patch.object(room, 'build_opener') as factory:
            factory.return_value.open.side_effect = URLError('offline')
            with self.assertRaises(room.RoomDataError):
                room.fetch_json('/api/occupancy')

    def test_real_router_uses_read_only_answer_before_generic_actions_or_ai(self):
        examples = [('How many people are in the room?', 'current'),
                    ("What was today's highest occupancy?", 'peak'),
                    ('When was the room busiest?', 'busiest'),
                    ('When was the last picture taken?', 'last_capture'),
                    ('How many pictures were analyzed today?', 'analyzed')]
        with patch.object(assistant, 'load_state', return_value={'paused': False}), \
             patch.object(assistant, 'status_emit'), patch.object(assistant, 'speak') as speak, \
             patch.object(assistant, 'room_info_answer', return_value='Saved result.') as answer, \
             patch.object(assistant, 'ask_ai') as ai, patch.object(assistant, 'take_picture') as camera, \
             patch.object(assistant, 'run', side_effect=AssertionError('No external commands')):
            for phrase, expected in examples:
                assistant.route(phrase)
                answer.assert_called_with(expected)
                speak.assert_called_with('Saved result.')
            ai.assert_not_called();camera.assert_not_called()
            answer.reset_mock()
            with patch.object(assistant, 'load_state', return_value={'paused': True}):
                assistant.route(examples[0][0])
            answer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
