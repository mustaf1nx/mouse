import sys, json, unittest, threading, time
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
from PIL import Image,ImageDraw
from text_answers import parse_answer
import client_mouse as c

class Tests(unittest.TestCase):
    def test_schema(self):
        payload=dict(status='ok',mode='multiple',confidence=.95,choices=[dict(x=.1,y=.7),dict(x=.1,y=.3)])
        self.assertEqual(parse_answer(json.dumps(payload))['choices'][0]['y'],.3)
        for bad in [[],[dict(x=2,y=.3)],[dict(x=.1,y=.3)]*2]:
            with self.assertRaises(ValueError):parse_answer(json.dumps(payload|dict(choices=bad)))
    def test_queue(self):
        a=c.Assistant.__new__(c.Assistant)
        image=Image.new('RGB',(500,300),'white')
        q=dict(choices=[dict(x=.1,y=.3),dict(x=.1,y=.7)],index=0,original=image,
               panel_box=(0,0,500,300),image_size=(500,300),question_rect=(0,0,500,300),
               rect=(0,0,500,300),window=1,desktop=(0,0,500,300),anchor=(200,100),deadline=time.monotonic()+120)
        a.choice_queue=q
        moves=[]
        a.animate_vertical=lambda start,end,duration: moves.append(end) or True
        a.signal_text_ready=lambda desktop:True
        with patch.object(c,'bounds',return_value=q['desktop']),patch.object(c,'region_unchanged',return_value=True),patch.object(c,'find_question_panel',return_value=q['panel_box']),patch.object(c,'capture',return_value=image):
            self.assertTrue(a.advance_choices((200,120)));self.assertEqual(q['index'],1)
            ImageDraw.Draw(image).rectangle((47,87,53,93),fill='black')
            self.assertTrue(a.advance_choices((200,120)));self.assertEqual(q['index'],2)
            self.assertTrue(a.advance_choices((200,120)));self.assertEqual(q['index'],2)
            q['original']=Image.new('RGB',(500,300),'white')
            ImageDraw.Draw(image).rectangle((200,30,210,40),fill='black')
            self.assertFalse(a.advance_choices((200,120)));self.assertIsNone(a.choice_queue)
        self.assertEqual(moves,[(200,90),(200,209)])
if __name__=='__main__':unittest.main()

