import unittest
from unittest.mock import patch
from jarvis.ui import jarvis_ironman as film
from jarvis.ui import jarvis_console_layout as layout
from jarvis.ui import jarvis_status as status
from jarvis.assistant import jarvis_assistant as assistant

class IronManTests(unittest.TestCase):
    def test_camera_chase_flyby_and_smooth_internal_transitions(self):
        hero=film.hero_pose(8.5)[0]
        eye,target,_=film.camera_pose(8.5,hero)
        self.assertLess(eye[2],hero[2])
        self.assertGreater(target[2],hero[2])
        t=9.3
        hero=film.hero_pose(t)[0]
        eye,target,roll=film.camera_pose(t,hero)
        camera=film.Camera(eye,target,143,47,roll)
        crossing,weight=film.drone_flyby(t)
        self.assertAlmostEqual(weight,1)
        self.assertLess(film.length(film.sub(crossing,film.enemy_position(t,0))),1e-9)
        local=camera.local(crossing)
        self.assertAlmostEqual(local[2],4)
        self.assertGreater(local[1],.9)
        self.assertGreater(camera.fx*3.7/local[2],70)
        for t in [8.3,10.3]:
            self.assertLess(film.length(film.sub(film.enemy_position(t+.0001,0),film.enemy_position(t-.0001,0))),.03)
        for t in [10.6,13.2,37,43,46]:
            before=film.camera_pose(t-.0001,film.hero_pose(t-.0001)[0])
            after=film.camera_pose(t+.0001,film.hero_pose(t+.0001)[0])
            for a,b in zip(before[:2],after[:2]):
                self.assertLess(film.length(film.sub(a,b)),.02)
        for n in range(470):
            t=n/10
            hero=film.hero_pose(t)[0]
            eye,target,roll=film.camera_pose(t,hero)
            self.assertGreater(film.length(film.sub(eye,target)),1)
            self.assertLess(abs(roll),.06)
            camera=film.Camera(eye,target,143,47,roll)
            chest=film.add(hero,(0,1.16,0))
            q=camera.project(camera.local(chest))
            self.assertIsNotNone(q)
            self.assertTrue(1<q[0]<142 and 2<q[1]<43,(t,q))

    def test_enemy_lifecycle_dodge_and_ballistic_damage_are_continuous(self):
        for index,hit in enumerate(film.HITS):
            self.assertEqual(film.enemy_state(film.enemy_spawn(index)-.01,index),'waiting')
            if index<5:self.assertEqual(film.enemy_state(hit-4,index),'pursuing')
            else:self.assertEqual(film.enemy_state(26,index),'encircling')
            self.assertEqual(film.enemy_state(hit-1.5,index),'attacking')
            self.assertEqual(film.enemy_state(hit-2.2,index),'evading')
            self.assertEqual(film.enemy_state(hit-.5,index),'crippled')
            self.assertEqual(film.enemy_state(hit,index),'destroyed')
            damage=hit-.8
            before=film.enemy_position(damage-.0001,index)
            after=film.enemy_position(damage+.0001,index)
            self.assertLess(film.length(film.sub(before,after)),.02)
            origin=film.enemy_formation(damage,index)
            velocity=film.mul(film.sub(origin,film.enemy_formation(damage-.01,index)),100)
            end=film.enemy_position(hit,index)
            self.assertLess(end[1],origin[1]+velocity[1]*.8-2)
            self.assertEqual(end,film.enemy_position(hit+1,index))

    def test_three_acts_encircle_hover_then_accelerate(self):
        self.assertEqual([label for _,label in film.ACTS],['I / PURSUIT','II / SURROUNDED','III / COMEBACK'])
        center=film.hero_pose(26)[0]
        offsets=[film.sub(film.enemy_position(26,i),center) for i in range(5,10)]
        for axis in [0,2]:
            self.assertLess(min(p[axis] for p in offsets),-7)
            self.assertGreater(max(p[axis] for p in offsets),7)
        self.assertEqual(film.flight_z(25),film.flight_z(34))
        self.assertGreater(film.flight_z(40)-film.flight_z(39),8.9)
        for t in [16,24,35,38]:
            self.assertLess(abs(film.flight_z(t+.0001)-film.flight_z(t-.0001)),.002)
        for index in range(5,10):
            for t in [33,film.HITS[index]-1.5]:
                self.assertLess(film.length(film.sub(film.enemy_position(t+.0001,index),film.enemy_position(t-.0001,index))),.03)

    def test_slow_motion_is_monotonic_and_preserves_musical_impacts(self):
        samples=[film.cinematic_time(n/100) for n in range(5401)]
        self.assertTrue(all(a<=b for a,b in zip(samples,samples[1:])))
        from jarvis.ui.jarvis_score import story_time,IMPACTS,CUES
        for seconds in [*IMPACTS,*(seconds for seconds,_ in CUES)]:
            self.assertAlmostEqual(film.cinematic_time(seconds),story_time(seconds))
        start,end=film.HITS[-2]+.08,film.HITS[-1]-.8
        self.assertLess(film.cinematic_time(45.0)-film.cinematic_time(44.9),.04)
        self.assertGreater(end,start)

    def test_enemy_bolts_commit_to_world_trajectory_and_expire(self):
        for index in range(len(film.HITS)):
            launches=film.enemy_volley(index)
            self.assertGreater(launches[1]-launches[0],1)
            for launched in launches:
                self.assertIsNone(film.enemy_bolt(launched-.01,index,launched))
                self.assertIsNone(film.enemy_bolt(launched+.86,index,launched))
                a=film.enemy_bolt(launched+.2,index,launched)[1]
                b=film.enemy_bolt(launched+.4,index,launched)[1]
                c=film.enemy_bolt(launched+.6,index,launched)[1]
                self.assertLess(film.length(film.sub(film.sub(b,a),film.sub(c,b))),1e-9)

    def test_depth_buffer_hides_far_geometry_independent_of_draw_order(self):
        canvas=film.Film(61,31,film.Camera((0,0,5),(0,0,0),60,30))
        canvas.triangle((-1,-1,0),(1,-1,0),(0,1,0),12)
        canvas.triangle((-1,-1,-2),(1,-1,-2),(0,1,-2),13)
        self.assertEqual(canvas.color[15][30],12)
        canvas.line((-1,0,-1),(1,0,-1),1,'=')
        self.assertEqual(canvas.color[15][30],12)

    def test_near_clipping(self):
        canvas=film.Film(61,31,film.Camera((0,0,0),(0,0,1),60,30))
        canvas.triangle((-1,-1,-.1),(1,-1,2),(0,1,2),12)
        self.assertTrue(any(c==12 for row in canvas.color for c in row))
        before=canvas.output()
        canvas.triangle((-1,-1,-2),(1,-1,-2),(0,1,-2),13)
        self.assertEqual(canvas.output(),before)

    def test_deterministic_six_shots_ascii_occlusion_and_responsive_bounds(self):
        signatures=[]
        for second in [2.7,10.8,19.3,31.2,40.5,51.5]:
            output=film.frame(120,40,second)
            self.assertEqual(output,film.frame(120,40,second))
            if second<47:
                self.assertTrue(any(c in {12,13} for _,_,_,c,_ in output))
            signatures.append(hash(tuple(output)))
            seen=set()
            for row,col,text,_,_ in output:
                self.assertTrue(text.isascii())
                self.assertTrue(0<=row<39 and 0<=col and col+len(text)<120)
                for x in range(col,col+len(text)):
                    self.assertNotIn((row,x),seen)
                    seen.add((row,x))
        self.assertEqual(len(set(signatures)),6)
        self.assertNotEqual(film.frame(80,24,19.2),film.frame(80,24,19.26))
        self.assertTrue(any(c==12 for _,_,_,c,_ in film.frame(120,40,47)))
        self.assertFalse(any(c==12 for _,_,_,c,_ in film.frame(120,40,53)))
        for width,height in [(5,4),(20,8),(80,24),(220,58)]:
            for row,col,text,_,_ in film.frame(width,height,40.5):
                self.assertLess(row,height-1)
                self.assertLess(col+len(text),width)

    def test_activation_and_existing_renderer_dispatch(self):
        data={'show':'ironman','show_started':'100','result':'running','stage':'action'}
        self.assertTrue(film.active(data,101))
        for invalid in [dict(data,attention='failure'),dict(data,result='0'),dict(data,show_started='nan')]:
            self.assertFalse(film.active(invalid,101))
        self.assertFalse(film.active(data,155))
        positions,_=layout.compose(data,{},80,24,'processing',status.reactor_lines,now=101)
        self.assertIn('IRON MAN',' '.join(item[2] for item in positions))

    def test_attacks_are_staged_inside_the_camera_frame(self):
        for index,hit in enumerate(film.HITS):
            t=hit-.1
            hero=film.hero_pose(t)[0]
            eye,target,roll=film.camera_pose(t,hero)
            camera=film.Camera(eye,target,143,47,roll)
            projected=camera.project(camera.local(film.enemy_position(t,index)))
            self.assertIsNotNone(projected)
            self.assertTrue(1<projected[0]<142,(index,projected))
            self.assertTrue(2<projected[1]<43,(index,projected))

    def test_voice_route_bypasses_ai_music_and_playback(self):
        for text in ['play iron man','hey jarvis play the iron man animation','show me skyfall','run the ironman film']:
            self.assertTrue(film.is_request(text),text)
        for text in ['delete iron man','what is iron man','play iron man by black sabbath']:
            self.assertFalse(film.is_request(text),text)
        with patch.object(assistant,'load_state',return_value={'paused':False}),patch.object(assistant,'run_ironman_show',return_value=True) as show,patch.object(assistant,'speak') as speak,patch.object(assistant,'ask_ai') as ai,patch.object(assistant,'status_emit'):
            assistant.route('Hey Jarvis, play the Iron Man animation.')
            show.assert_called_once();speak.assert_not_called();ai.assert_not_called()

    def test_reset_cancellation_and_cleanup(self):
        with patch('jarvis.computer.jarvis_reset.generation',side_effect=['before','after']),patch('jarvis.ui.jarvis_status.emit') as emit,patch.object(film.time,'monotonic',side_effect=[0,0]):
            self.assertFalse(film.run_show())
            self.assertEqual(emit.call_args.kwargs,{'show':'','show_started':'','show_duration':'','show_audio_socket':''})
        with patch('jarvis.computer.jarvis_reset.generation',return_value='same'),patch('jarvis.ui.jarvis_status.emit'),patch.object(film.time,'monotonic',side_effect=[0,55]):
            self.assertTrue(film.run_show())

if __name__=='__main__': unittest.main()
