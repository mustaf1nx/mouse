"""Locate one pale cyan question panel without fixed screen coordinates."""
from collections import deque
import math
from PIL import Image


class PanelNotFound(ValueError):
    pass


def find_question_panel(image, anchor=None):
    original_w, original_h = image.size
    scale = min(1.0, 960 / max(image.size))
    w, h = max(1, round(original_w * scale)), max(1, round(original_h * scale))
    sample = image.convert('RGB').resize((w, h), Image.Resampling.NEAREST)
    rgb = sample.tobytes()
    mask = bytearray(
        170 <= r <= 248 and g >= 190 and b >= 190
        and g-r >= 5 and b-r >= 7 and -4 <= b-g <= 30
        for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3])
    )
    candidates = []
    for index in range(w*h):
        if not mask[index]:
            continue
        mask[index] = 0
        queue = deque([index])
        left = right = index % w
        top = bottom = index // w
        area = 0
        while queue:
            current = queue.popleft()
            x, y = current % w, current // w
            area += 1
            left, right = min(left,x), max(right,x)
            top, bottom = min(top,y), max(bottom,y)
            for neighbour in (current-1 if x else -1,
                              current+1 if x+1<w else -1,
                              current-w if y else -1,
                              current+w if y+1<h else -1):
                if neighbour >= 0 and mask[neighbour]:
                    mask[neighbour] = 0
                    queue.append(neighbour)
        width, height = right-left+1, bottom-top+1
        if (width >= max(80,w*.28) and height >= max(24,h*.035)
                and area >= w*h*.012 and area/(width*height) >= .50
                and width*height <= w*h*.85):
            candidates.append((left,top,right+1,bottom+1))
    if not candidates:
        raise PanelNotFound('No blue question block found; show one complete question with its answers.')
    if len(candidates) > 1:
        if anchor is None:
            raise PanelNotFound('Multiple blue question blocks found; point at the desired question.')
        ax, ay = anchor[0]*w/original_w, anchor[1]*h/original_h
        selected = [box for box in candidates if box[0] <= ax < box[2] and box[1] <= ay < box[3]]
        if not selected:
            # The pointer may intentionally be to the left/right for vertical indication.
            selected = [box for box in candidates if box[1] <= ay < box[3]]
        if len(selected) != 1:
            raise PanelNotFound('Multiple blue question blocks found; move cursor inside the desired block or beside it at the same height.')
        candidates = selected
    left,top,right,bottom = candidates[0]
    edge_margin = max(2, math.ceil(6*w/original_w))
    if left <= edge_margin or top <= edge_margin or right >= w-edge_margin or bottom >= h-edge_margin:
        raise PanelNotFound('Selected question touches the window edge; scroll until this question is fully visible.')
    return (math.floor(left*original_w/w), math.floor(top*original_h/h),
            min(original_w,math.ceil(right*original_w/w)),
            min(original_h,math.ceil(bottom*original_h/h)))


def panel_screen_rect(box, image_size, window_rect):
    left, top, right, bottom = box
    iw, ih = image_size
    wx, wy, ww, wh = window_rect
    x1, y1 = wx+round(left*ww/iw), wy+round(top*wh/ih)
    x2, y2 = wx+round(right*ww/iw), wy+round(bottom*wh/ih)
    return x1,y1,max(1,x2-x1),max(1,y2-y1)
