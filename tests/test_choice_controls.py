from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image,ImageDraw
from choice_controls import choice_position

class Tests(unittest.TestCase):
    def fixture(self):
        image=Image.new('RGB',(600,240),(230,242,244))
        draw=ImageDraw.Draw(image)
        for y in (65,110,155,200):
            draw.ellipse((22,y-8,38,y+8),fill='white',outline=(140,140,140),width=1)
        return image
    def test_index_ignores_wrong_ai_coordinates(self):
        image=self.fixture()
        target=dict(choice_index=2,choice_count=4,x=.01,y=.01)
        point,_=choice_position(image,target,(100,300,600,240))
        self.assertEqual(point,(130,410))
    def test_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            choice_position(self.fixture(),dict(choice_index=2,choice_count=3),(0,0,600,240))
    def test_missing_index_rejected(self):
        with self.assertRaises(ValueError):
            choice_position(self.fixture(),dict(x=.1,y=.2),(0,0,600,240))

if __name__=='__main__':unittest.main()
