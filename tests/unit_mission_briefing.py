from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jarvis.assistant import mission_briefing as briefing
from jarvis.assistant import jarvis_assistant as assistant
from jarvis.ui import jarvis_console_layout as layout
from jarvis.ui import jarvis_status as status


def source(day='2026-10-21'):
    return f'''# This is synthetic test content.
DATE: {day}
MISSION: Bring gesture controls online
TASKS:
- Test classroom lighting
- Tune the thresholds
ASSIGNMENTS:
- Xavier: record the results
SUCCESS: Five successful detections in a row
'''


class MissionBriefingTests(unittest.TestCase):
    def test_fields_comments_aliases_and_date_warning(self):
        value = briefing.parse(source(), date(2026, 10, 21))
        self.assertEqual(value['date_warning'], '')
        self.assertEqual(value['tasks'], ['Test classroom lighting', 'Tune the thresholds'])
        self.assertEqual(value['assignments'], ['Xavier: record the results'])
        for day in ['2026-10-20', '2026-10-22']:
            value = briefing.parse(source(day), date(2026, 10, 21))
            self.assertIn(day, value['date_warning'])
            self.assertIn('not today', briefing.spoken(value))
        value = briefing.parse(source().replace('MISSION:', 'OBJECTIVE:').replace('SUCCESS:', 'SUCCESS CONDITION:'), date(2026, 10, 21))
        self.assertEqual(value['mission'], 'Bring gesture controls online')

    def test_optional_sections_and_file_validation(self):
        basic = 'DATE: 2026-10-21\nMISSION: Test\nTASKS:\n- One task\n'
        self.assertEqual(briefing.parse(basic)['assignments'], [])
        for text in [basic.replace('2026-10-21', '2026-02-30'), basic + 'DATE: 2026-10-21\n',
                     basic.replace('MISSION: Test', 'MISSION:'), basic.replace('- One task', '# no tasks'),
                     basic + 'COMMAND: do something\n', basic.replace('Test', 'Test\x1b[31m'),
                     basic.replace('- One task', '- ' + 'x' * 241), basic + '- Extra\n' * 12]:
            with self.subTest(text=text), self.assertRaises(briefing.BriefingError):
                briefing.parse(text)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'briefing.txt'
            with self.assertRaises(briefing.BriefingError):
                briefing.load(path)
            for content in [b'\xff', b'x' * (briefing.MAX_BYTES + 1)]:
                path.write_bytes(content)
                with self.assertRaises(briefing.BriefingError):
                    briefing.load(path)
            path.write_bytes(b'\xef\xbb\xbf' + basic.encode())
            self.assertEqual(briefing.load(path)['tasks'], ['One task'])

    def test_exact_voice_requests_do_not_claim_unrelated_commands(self):
        for text in ['mission briefing', 'jarvis mission briefing', 'give me the mission briefing',
                     'hey jarvis please read the daily briefing', "today's mission", 'today s mission',
                     'start the mission briefing please']:
            self.assertTrue(briefing.is_briefing_request(text), text)
        for text in ['play mission impossible', 'delete the mission briefing', 'what is a mission briefing',
                     'take a picture', 'mission complete']:
            self.assertFalse(briefing.is_briefing_request(text), text)

    def test_real_route_reads_file_and_emits_a_persistent_visual_without_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mission.txt'
            path.write_text(source(date.today().isoformat()))
            state = Path(folder) / 'state.json'
            spoken = []
            def silent_speech(message):
                spoken.append(message)
                status.emit('speaking', 'Silent integration test.', reply=message)
            def present(speak, emit):
                return briefing.present(speak, emit, startup=0)
            with patch.dict(os.environ, {'JARVIS_BRIEFING_FILE': str(path), 'JARVIS_STATUS_FILE': str(state)}), \
                 patch.object(assistant, 'load_state', return_value={'paused': False}), \
                 patch.object(assistant, 'speak', side_effect=silent_speech), \
                 patch.object(assistant, 'present_briefing', side_effect=present), \
                 patch.object(assistant, 'ask_ai') as ai, \
                 patch.object(assistant, 'run', side_effect=AssertionError('No external commands in this test')):
                assistant.route('Jarvis, mission briefing.')
                self.assertEqual(len(spoken), 1)
                self.assertIn('Task 1. Test classroom lighting', spoken[0])
                ai.assert_not_called()
                status.emit('complete', 'Done.', result='0')
                data = status.read_state(state)
                self.assertTrue(briefing.active(data))
                positions, _ = layout.compose(data, {}, 144, 48, 'standby', status.reactor_lines,
                                              now=float(data['briefing_started']) + 3)
                rendered = '\n'.join(item[2] for item in positions)
                self.assertIn('MISSION CONTROL', rendered)
                self.assertIn('Test classroom lighting', rendered)
                self.assertIn('Five successful detections', rendered)

    def test_pause_missing_file_and_cancellation(self):
        with patch.object(assistant, 'load_state', return_value={'paused': True}), \
             patch.object(assistant, 'present_briefing') as present:
            assistant.route('mission briefing')
            present.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'missing.txt'
            with patch('jarvis.computer.jarvis_reset.generation', return_value='test'):
                messages, events = [], []
                self.assertFalse(briefing.present(messages.append, lambda *a, **k: events.append(k), path=path, startup=0))
                self.assertIn('needs an update', messages[0])
                self.assertEqual(events, [{'briefing_payload': '', 'briefing_started': ''}])
            path.write_text(source())
            with patch('jarvis.computer.jarvis_reset.generation', side_effect=['before', 'after']):
                messages = []
                self.assertFalse(briefing.present(messages.append, lambda *a, **k: None, path=path, startup=0))
                self.assertEqual(messages, [])

    def test_responsive_animation_unicode_bounds_and_scroll_reach_every_task(self):
        value = briefing.parse(source(), date(2026, 10, 21))
        value['tasks'] = [f'Task {index} ' + '測試 café e\u0301 ' * 12 for index in range(12)]
        data = {'briefing_payload': json.dumps(value), 'briefing_started': '100', 'started': '100',
                'stage': 'speaking', 'result': 'running'}
        for width, height in [(220, 58), (144, 48), (100, 40), (80, 24), (40, 12), (20, 8), (5, 4)]:
            for now in [100, 101, 103]:
                seen = set()
                positions, content_width = layout.compose(data, {}, width, height, 'speaking', status.reactor_lines, now=now)
                for row, col, line, style, limit in positions:
                    self.assertLess(row, height - 1)
                    self.assertLess(col + layout.cells(line), width)
                    for cell in range(col, col + layout.cells(line)):
                        self.assertNotIn((row, cell), seen)
                        seen.add((row, cell))
            last = briefing.scroll_limit(data, content_width, height)
            self.assertGreaterEqual(last, 0)
            positions, _ = layout.compose(data, {}, width, height, 'speaking', status.reactor_lines, now=103, scroll=last)
            if width >= 40:
                self.assertIn('row', ' '.join(item[2] for item in positions))
        self.assertFalse(briefing.active(dict(data, stage='listening')))
        self.assertFalse(briefing.active(dict(data, attention='A real problem')))
        self.assertFalse(briefing.active(dict(data, briefing_payload='not json')))

    def test_styled_cards_use_space_without_hiding_short_task_lists(self):
        value = briefing.parse('DATE: 2026-10-21\nMISSION: Prepare the group project\nTASKS:\n' +
                               '\n'.join('- Group task ' + str(index) for index in range(1, 6)), date(2026, 10, 21))
        data = {'briefing_payload': json.dumps(value), 'briefing_started': '100',
                'stage': 'complete', 'result': '0'}
        for width, height in [(80, 24), (120, 34), (144, 48)]:
            positions, _ = layout.compose(data, {}, width, height, 'standby', status.reactor_lines, now=104)
            rendered = '\n'.join(item[2] for item in positions)
            self.assertIn('PRIMARY OBJECTIVE', rendered)
            self.assertIn('05 DIRECTIVES', rendered)
            self.assertIn('MISSION READY', rendered)
            self.assertIn('Group task 5', rendered)
            self.assertNotIn('TEAM ASSIGNMENTS', rendered)
            self.assertNotIn('SUCCESS CONDITION', rendered)
            self.assertTrue(any('╭' in item[2] for item in positions))
            if width >= 120:
                self.assertIn('JARVIS CORE', rendered)


if __name__ == '__main__':
    unittest.main()
