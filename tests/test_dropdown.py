import sys,json,time,threading,unittest
from unittest.mock import patch,Mock,AsyncMock
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src'))
from PIL import Image,ImageDraw
import client_mouse as c
from dropdown_support import question_stable
from text_answers import parse_answer

ROW=dict(label='Binary search',answer='O(log n)',field=dict(left=.2,top=.5,right=.7,bottom=.6))
TARGET=dict(status='ok',mode='menu',confidence=.95,x=.4,y=.75,
            menu=dict(left=.2,top=.5,right=.7,bottom=.9),option=dict(left=.2,top=.7,right=.7,bottom=.8))
class Tests(unittest.TestCase):
    def test_schema(self):
        self.assertEqual(parse_answer('```json\n'+json.dumps(TARGET)+'\n```')['mode'],'menu')
        with self.assertRaises(ValueError):parse_answer(json.dumps(TARGET)+' trailing text')
        self.assertEqual(parse_answer(json.dumps(dict(status='ok',mode='dropdown',confidence=.80,rows=[ROW])))['mode'],'dropdown')
        with self.assertRaises(ValueError):parse_answer(json.dumps(TARGET|dict(confidence=.80)))
        with self.assertRaises(ValueError):parse_answer(json.dumps(dict(status='ok',mode='dropdown',confidence=.79,rows=[ROW])))
        self.assertEqual(parse_answer(json.dumps(dict(status='ok',mode='dropdown',confidence=.95,rows=[ROW])))['mode'],'dropdown')
        self.assertEqual(parse_answer(json.dumps(TARGET))['mode'],'menu')
        for change in [dict(confidence=.5),dict(x=.9),dict(menu=dict(left=0,top=0,right=1,bottom=1)),dict(option=dict(left=.1,top=.7,right=.7,bottom=.8))]:
            with self.assertRaises(ValueError):parse_answer(json.dumps(TARGET|change))
    def test_comparison(self):
        before=Image.new('RGB',(500,300),'white');after=before.copy()
        ImageDraw.Draw(after).rectangle((110,155,160,170),fill='black')
        self.assertTrue(question_stable(before,after,[ROW],(0,0,500,300)))
        ImageDraw.Draw(after).rectangle((20,20,30,30),fill='black')
        self.assertFalse(question_stable(before,after,[ROW],(0,0,500,300)))
    def build(self):
        a=c.Assistant.__new__(c.Assistant);image=Image.new('RGB',(500,300),'white')
        a.controller=SimpleNamespace(position=(200,180));a.cancel=threading.Event()
        a.animate_vertical=Mock(return_value=True);a.signal_text_ready=Mock(return_value=True)
        a.dropdown_queue=dict(rows=[ROW],index=0,original=image.copy(),panel_box=(0,0,500,300),image_size=image.size,
            rect=(0,0,500,300),question_rect=(0,0,500,300),window=1,desktop=(0,0,500,300),deadline=time.monotonic()+180)
        return a,image
    def test_indication_then_manual_click(self):
        a,image=self.build();result=Mock();result.json.return_value=dict(success=True,target=TARGET)
        with patch.object(c,'bounds',return_value=(0,0,500,300)),patch.object(c,'region_unchanged',return_value=True),patch.object(c,'capture',return_value=image),patch.object(c.requests,'post',return_value=result) as post:
            self.assertTrue(a.advance_dropdown((200,180)))
            self.assertEqual(a.dropdown_queue['index'],0)
            self.assertIn('menu_context',post.call_args.kwargs['data'])
            a.dropdown_click(200,225,c.mouse.Button.left,True)
            self.assertEqual(a.dropdown_queue['index'],1)
            self.assertTrue(a.advance_dropdown((200,225)))
        a.animate_vertical.assert_called_once_with((200,180),(200,224),.8)
    def test_menu_changed_no_move(self):
        a,image=self.build();changed=image.copy();ImageDraw.Draw(changed).rectangle((150,200,160,210),fill='black')
        result=Mock();result.json.return_value=dict(success=True,target=TARGET)
        with patch.object(c,'bounds',return_value=(0,0,500,300)),patch.object(c,'region_unchanged',return_value=True),patch.object(c,'capture',side_effect=[image,changed]),patch.object(c.requests,'post',return_value=result):
            self.assertTrue(a.advance_dropdown((200,180)))
            a.animate_vertical.assert_not_called()
            self.assertNotIn('awaiting_click',a.dropdown_queue)
    def test_wrong_click_no_advance(self):
        a,_=self.build();a.dropdown_queue['awaiting_click']=(100,200,350,240)
        a.dropdown_click(20,20,c.mouse.Button.left,True)
        self.assertEqual(a.dropdown_queue['index'],0)
    def test_expired(self):
        a,_=self.build();a.dropdown_queue['deadline']=0
        self.assertFalse(a.advance_dropdown((200,180)));self.assertIsNone(a.dropdown_queue)
    def test_scroll_retains_context_but_clears_stale_click(self):
        a,_=self.build();a.dropdown_queue['index']=3
        a.dropdown_queue['awaiting_click']=(100,200,300,240)
        a.request_cancel=Mock();a.choice_queue={}
        a.on_scroll(200,200,0,-1)
        self.assertEqual(a.dropdown_queue['index'],3)
        self.assertNotIn('awaiting_click',a.dropdown_queue)
        self.assertIsNone(a.choice_queue)
        a.request_cancel.assert_called_once()

if __name__=='__main__':unittest.main()

