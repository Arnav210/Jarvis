"""Silent regression checks for computer inspection and bounded tool planning."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jarvis.computer import jarvis_computer as computer

def response(name=None, **arguments):
    return {'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': name, 'arguments': arguments}}]} if name else {'role': 'assistant', 'content': 'Done.'}

class ComputerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.project = self.home / 'Jarvis'
        self.music = self.project / 'data/music'
        self.music.mkdir(parents=True)
        (self.music / 'one.mp3').write_bytes(b'a' * 3000)
        (self.music / 'two.mp3').write_bytes(b'b' * 7000)
        self.patches = [patch.object(computer, 'HOME', self.home), patch.object(computer, 'PROJECT', self.project), patch.object(computer, 'RUNTIME', self.home / 'runtime'), patch.object(computer, 'emit')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_measurement_and_largest(self):
        result = computer.inspect_path('music', 'largest_files')
        self.assertEqual(result['bytes'], 10000)
        self.assertEqual(result['files'], 2)
        self.assertFalse(result['partial'])
        self.assertEqual(result['entries'][0]['bytes'], 7000)
        self.assertEqual(computer.inspect_path('Jarvis', 'children')['entries'][0]['bytes'], 10000)

    def test_path_boundary_and_links(self):
        with self.assertRaises(ValueError):
            computer.resolve_path(str(self.home.parent))
        if os.name != 'nt':
            (self.music / 'loop').symlink_to(self.music, target_is_directory=True)
            (self.music / 'escape').symlink_to('/etc', target_is_directory=True)
            result = computer.inspect_path('music')
            self.assertEqual(result['bytes'], 10000)
            self.assertEqual(result['skipped_links_or_mounts'], 2)
            with self.assertRaises(ValueError):
                computer.resolve_path(str(self.music / 'escape'))

    def test_partial_scans_are_labeled(self):
        files, details = computer.scan(self.music, maximum=1)
        self.assertTrue(details['partial'])
        with patch.object(computer, 'scan', return_value=(files, details)):
            self.assertIn('partial', computer.inspect_path('music')['summary'])

    def test_multi_step_planning_uses_real_result(self):
        replies = iter([response('find_paths', query='music', base='Jarvis', kind='directory'), response('inspect_path', path=str(self.music)), response()])
        observed = []
        def model(messages, timeout):
            observed.append(json.loads(json.dumps(messages)))
            return next(replies)
        answer = computer.ask('Find the music folder and measure it.', model_call=model)
        self.assertIn('9.8 KiB', answer)
        self.assertEqual(observed[1][-1]['role'], 'tool')
        self.assertIn(str(self.music), observed[1][-1]['content'])
        self.assertEqual(computer.read_context()['path'], str(self.music))
        self.assertTrue(computer.is_computer_request("What's inside it?"))
        self.assertFalse(computer.is_computer_request('Play some Bruno Mars'))

    def test_comparison_keeps_both_measurements(self):
        replies = iter([{'role': 'assistant', 'tool_calls': [response('inspect_path', path='music')['tool_calls'][0], response('inspect_path', path='Jarvis')['tool_calls'][0]]}, response()])
        answer = computer.ask('Compare music and Jarvis storage.', model_call=lambda *_: next(replies))
        self.assertIn(str(self.music), answer)
        self.assertIn(str(self.project) + ':', answer)

    def test_unverified_claims_and_unknown_tools_rejected(self):
        answer = computer.ask('How much RAM?', model_call=lambda *_: {'role': 'assistant', 'content': 'You have 999 GB of RAM.'})
        self.assertNotIn('999', answer)
        answer = computer.ask('Read disk space', model_call=lambda *_: response('run_shell', command='touch never-created'))
        self.assertIn('could not complete', answer)
        self.assertFalse((self.project / 'never-created').exists())
        answer = computer.ask('Delete the music folder', model_call=lambda *_: self.fail('Mutation reached model'))
        self.assertIn('inspection only', answer)
        self.assertTrue(self.music.exists())

    def test_service_arguments_are_read_only(self):
        with patch.object(computer.subprocess, 'run') as run:
            run.return_value.stdout = 'LoadState=loaded\nActiveState=active\nSubState=running\n'
            self.assertEqual(computer.service_status('jarvis-wake')['ActiveState'], 'active')
            self.assertIn('show', run.call_args.args[0])
            self.assertNotIn('restart', run.call_args.args[0])
        with self.assertRaises(ValueError):
            computer.service_status('--help;touch test')

    def test_invalid_tool_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            computer.inspect_path('music', view='delete')
        with self.assertRaises(TypeError):
            computer.inspect_path('music', command='rm')

    def test_requested_listing_count_is_honored(self):
        self.assertEqual(computer.listing_limit('the three largest files'), 3)
        self.assertEqual(computer.listing_limit('top 2 folders'), 2)
        replies = iter([response('inspect_path', path='music', view='largest_files'), response()])
        with patch.dict(computer.FUNCTIONS, {'inspect_path': unittest.mock.Mock(wraps=computer.inspect_path)}):
            computer.ask('Show the three largest files in music', model_call=lambda *_: next(replies))
            self.assertEqual(computer.FUNCTIONS['inspect_path'].call_args.kwargs['limit'], 3)

if __name__ == '__main__':
    unittest.main()
