from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from jarvis.ui import jarvis_birthday as birthday
from jarvis.ui import jarvis_console_layout as layout
from jarvis.assistant import jarvis_assistant as assistant


class BirthdayTests(unittest.TestCase):
    def test_expiry_disable_and_private_message(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'birthday.json'
            data={'enabled':True,'date':'2026-10-21','honoree':'Mr. Mort','message':'The exact supplied message.\nSecond paragraph.'}
            path.write_text(json.dumps(data))
            with patch.object(birthday,'config_path',return_value=path):
                self.assertEqual(birthday.load(date(2026,10,21)),data)
                with self.assertRaises(ValueError):birthday.load(date(2026,10,22))
                birthday.disable()
                with self.assertRaises(ValueError):birthday.load(date(2026,10,21))
                self.assertEqual(json.loads(path.read_text())['message'],data['message'])

    def test_exact_speech_and_normal_return_on_completion_cancel_and_failure(self):
        data={'honoree':'Mr. Mort','message':'Attention all students.\nExact message.'}
        for cancelled in [False,True]:
            speaker=Mock();emit=Mock()
            with patch.object(birthday,'load',return_value=data),patch('jarvis.computer.jarvis_reset.generation',side_effect=['a','a','b' if cancelled else 'a']),patch.object(birthday.time,'monotonic',side_effect=[0,0,45]),patch.object(birthday.time,'sleep'):
                self.assertEqual(birthday.present(speaker,emit),not cancelled)
            speaker.assert_called_once_with(data['message'])
            self.assertEqual(emit.call_args.kwargs['show'],'')
        with patch.object(birthday,'load',return_value=data),patch('jarvis.computer.jarvis_reset.generation',return_value='a'):
            emit=Mock()
            with self.assertRaises(RuntimeError):birthday.present(Mock(side_effect=RuntimeError('speech')),emit)
            self.assertEqual(emit.call_args.kwargs['show'],'')

    def test_render_bounds_animation_cameo_and_console_dispatch(self):
        for w,h in [(5,4),(20,8),(80,24),(120,40),(220,58)]:
            for t in [0,4,12,16,19,20.2,25,44.9]:
                for y,x,text,_,_ in birthday.frame(w,h,t,'Mr. Mort'):
                    self.assertTrue(text.isascii())
                    self.assertTrue(0<=y<h-1 and 0<=x and x+len(text)<w)
        self.assertNotEqual(birthday.frame(120,40,25,'Mr. Mort'),birthday.frame(120,40,25.2,'Mr. Mort'))
        data={'show':'birthday','show_started':'100','result':'running','show_honoree':'Mr. Mort'}
        self.assertTrue(birthday.active(data,110));self.assertFalse(birthday.active(data,146))
        self.assertFalse(birthday.active(dict(data,attention='error'),110))
        result,_=layout.compose(data,{},120,40,'speaking',lambda *args:[],now=110)
        self.assertIn('MR. MORT',' '.join(row[2] for row in result))

    def test_voice_route_is_explicit_and_does_not_use_ai_or_music(self):
        for text in ['birthday protocol','hey jarvis activate birthday protocol','please start the birthday protocol']:
            self.assertTrue(birthday.is_request(text))
        for text in ['when is my birthday','play birthday music','explain birthday protocol']:
            self.assertFalse(birthday.is_request(text))
        with patch.object(assistant,'load_state',return_value={'paused':False}),patch.object(assistant,'status_emit'),patch.object(assistant,'present_birthday') as present,patch.object(assistant,'speak') as speaker,patch.object(assistant,'ask_ai') as ai:
            assistant.route('Hey Jarvis, birthday protocol.')
            present.assert_called_once();speaker.assert_not_called();ai.assert_not_called()


if __name__=='__main__':unittest.main()
