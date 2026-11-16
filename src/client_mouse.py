"""Windowless mouse assistant. Never generates clicks."""
import ctypes
import io
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time

if sys.platform == 'win32':
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

import requests
from dotenv import load_dotenv
from PIL import ImageGrab, ImageChops, ImageDraw
from pynput import mouse, keyboard
from targeting import parse_target, screen_point, eased_point
from window_region import select_region, region_unchanged
from question_panel import find_question_panel, panel_screen_rect, PanelNotFound
from text_answers import parse_answer, field_box, contains, same_question
from text_entry import copy_text, type_checked
from dropdown_support import DropdownFlow
from choice_controls import choice_position

BASE = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
load_dotenv(BASE / 'client.env', override=True)
SERVER = os.getenv('SERVER_URL', 'http://localhost:8000').rstrip('/')
TOKEN = os.getenv('AUTH_TOKEN', '')
log_dir = Path(os.getenv('LOCALAPPDATA', str(Path.home() / 'Library' / 'Logs'))) / 'MouseAssistant'
log_dir.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(log_dir / 'client.log', maxBytes=1000000, backupCount=2, encoding='utf-8')
logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()], format='%(asctime)s %(message)s')


def bounds():
    if sys.platform == 'win32':
        return (0, 0, ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1))
    if sys.platform == 'darwin':
        import Quartz
        rect = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        return (int(rect.origin.x), int(rect.origin.y), int(rect.size.width), int(rect.size.height))
    raise RuntimeError('Only Windows and macOS are supported')


def capture(rect):
    x, y, w, h = rect
    # Normalized coordinates also handle a Retina image larger than logical bounds.
    return ImageGrab.grab(bbox=(x, y, x + w, y + h)).convert('RGB')


class Assistant(DropdownFlow):
    def __init__(self):
        self.controller = mouse.Controller()
        self.typer = keyboard.Controller()
        self.pending_lock = threading.Lock()
        self.pending_text = None
        self.choice_queue = None
        self.dropdown_queue = None
        self.text_click = None
        self.typing_text = False
        self.cancel = threading.Event()
        self.cancel_reason = None
        self.quit = threading.Event()
        self.busy = threading.Lock()
        self.middle_down = None
        self.right_alt_down = False
        self.mouse5_down = False
        mouse_options = {'win32_event_filter': self.filter_mouse} if sys.platform == 'win32' else {}
        key_options = {'win32_event_filter': self.filter_keyboard} if sys.platform == 'win32' else {}
        self.listener = mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll, **mouse_options)
        self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press, on_release=self.on_key_release, **key_options)

    def trigger(self, source):
        if self.quit.is_set():
            return
        if not self.busy.acquire(blocking=False):
            logging.info('BUSY: %s ignored; previous request still running', source)
            return
        self.clear_pending_text()
        self.cancel_reason = None
        self.cancel.clear()
        logging.info('TRIGGER: %s', source)
        try:
            threading.Thread(target=self.run_request, daemon=True).start()
        except Exception:
            self.busy.release()
            raise

    @staticmethod
    def is_right_alt(key):
        return key in (keyboard.Key.alt_r, keyboard.Key.alt_gr)

    def on_key_press(self, key):
        if self.typing_text:
            return
        if not self.is_right_alt(key) and self.pending_text is not None:
            self.request_cancel("manual keyboard input; pending text entry cancelled")
        if self.is_right_alt(key) and not self.right_alt_down:
            self.right_alt_down = True
            self.trigger('Right Alt')

    def on_key_release(self, key):
        if self.is_right_alt(key):
            self.right_alt_down = False

    def filter_keyboard(self, msg, data):
        if self.typing_text:
            if getattr(data, 'flags', 0) & 0x10:
                return False  # Ignore our injected characters in the listener, not in the target app.
            if msg in (0x100, 0x104):
                self.request_cancel('manual key pressed during text entry')
        # Reserve Right Alt only; leave all other keyboard input untouched.
        if data.vkCode == 0xA5 and msg in (0x100, 0x104, 0x101, 0x105):
            if msg in (0x100, 0x104):
                self.on_key_press(keyboard.Key.alt_r)
            else:
                self.on_key_release(keyboard.Key.alt_r)
            self.keyboard_listener.suppress_event()
            return False
        return True

    def filter_mouse(self, msg, data):
        if msg in (0x207, 0x208):
            self.on_click(data.pt.x, data.pt.y, mouse.Button.middle, msg == 0x207)
            self.listener.suppress_event()  # Avoid browser autoscroll on the trigger.
            return False
        # Mouse 5 normally navigates Forward in browsers; suppress that action.
        if msg in (0x20B, 0x20C) and ((data.mouseData >> 16) & 0xFFFF) == 2:
            self.on_click(data.pt.x, data.pt.y, mouse.Button.x2, msg == 0x20B)
            self.listener.suppress_event()
            return False
        return True

    def request_cancel(self, reason):
        self.clear_pending_text()
        if not self.cancel.is_set():
            self.cancel_reason = reason
            if self.busy.locked():
                logging.info('CANCEL: %s', reason)
        self.cancel.set()

    def on_scroll(self, x, y, dx, dy):
        # Scrolling a native select must not discard its question context.
        # The next request still validates window, question and popup pixels.
        if getattr(self, 'dropdown_queue', None) is not None:
            self.dropdown_queue.pop('awaiting_click', None)
            logging.info('DROPDOWN: scroll detected; keep context and revalidate on next trigger')
        self.choice_queue = None
        self.request_cancel('wheel scrolled (dx=%s, dy=%s)' % (dx, dy))

    def on_click(self, x, y, button, pressed):
        self.dropdown_click(x, y, button, pressed)
        if self.typing_text and pressed:
            self.request_cancel('mouse clicked during text entry')
            return
        if button == mouse.Button.left and self.handle_text_click(x, y, pressed):
            return
        now = time.monotonic()
        if button == getattr(mouse.Button, 'x2', None):
            if pressed and not self.mouse5_down:
                self.mouse5_down = True
                self.trigger('Mouse 5')
            elif not pressed:
                self.mouse5_down = False
            return
        if button != mouse.Button.middle:
            if pressed:
                self.request_cancel('mouse button pressed: %s' % button.name)
            return
        if pressed:
            logging.info('MIDDLE: button pressed')
            self.middle_down = now
            return
        if self.middle_down is None:
            return
        held = now - self.middle_down
        self.middle_down = None
        if held >= 2:
            self.request_cancel('exit requested by holding middle button')
            self.quit.set()
        else:
            self.trigger('single middle click')

    def run_request(self):
        try:
            # Let application reactions to the trigger settle before capture.
            if self.cancel.wait(0.3):
                return
            start = tuple(self.controller.position)
            if getattr(self, 'dropdown_queue', None) is not None and self.advance_dropdown(start):
                return
            if self.choice_queue is not None and self.advance_choices(start):
                return
            desktop = bounds()
            rect, window = select_region(start, desktop)
            logging.info('REGION: capturing question window (%s x %s)', rect[2], rect[3])
            full_image = capture(rect)
            panel_anchor = ((start[0]-rect[0])*full_image.width/rect[2],
                            (start[1]-rect[1])*full_image.height/rect[3])
            panel_box = find_question_panel(full_image, anchor=panel_anchor)
            question_rect = panel_screen_rect(panel_box, full_image.size, rect)
            original = full_image.crop(panel_box)
            logging.info('PANEL: blue question block found at %s; only this area is sent and compared', question_rect)
            logging.info('CAPTURE: question captured (%s x %s)', *original.size)
            buf = io.BytesIO()
            original.save(buf, format='PNG')
            started = time.monotonic()
            logging.info('SEND: uploading screenshot to local/configured server')
            response = requests.post(SERVER + '/analyze-target',
                files={'file': ('screen.png', buf.getvalue(), 'image/png')},
                headers={'X-Auth-Token': TOKEN} if TOKEN else {}, timeout=(10, 90))
            logging.info('SERVER: HTTP %s', response.status_code)
            if response.status_code == 503:
                raise RuntimeError('Server has no Claude key. Set ANTHROPIC_API_KEY in .env and restart server.')
            response.raise_for_status()
            result = response.json()
            if not result.get('success'):
                logging.warning('ANALYSIS [%s]: %s', result.get('error_code', 'unknown'), result.get('error', 'Analysis failed'))
                return
            import json
            target = parse_answer(json.dumps(result['target']))
            logging.info('ANSWER: valid %s answer received', target.get('mode', 'choice'))
            elapsed = time.monotonic() - started
            if self.cancel.is_set():
                logging.info('DISCARD: response ignored after %.1fs; reason: %s', elapsed, self.cancel_reason or 'shutdown')
                return
            if elapsed > 30:
                logging.info('CANCEL: response too old (%.1fs, limit 30s)', elapsed)
                return
            if bounds() != desktop or not region_unchanged(window, rect, bounds()):
                logging.info('CANCEL: question window or display geometry changed')
                return
            if tuple(self.controller.position) != start:
                logging.info('CANCEL: cursor moved while waiting')
                return
            fresh_full = capture(rect)
            fresh_box = find_question_panel(fresh_full, anchor=panel_anchor)
            if fresh_full.size != full_image.size or fresh_box != panel_box:
                logging.info('CANCEL: question block moved or changed size')
                return
            fresh = fresh_full.crop(panel_box)
            if not same_question(original, fresh, target.get('field') if target.get('mode') == 'text' else None):
                logging.info('CANCEL: contents inside blue question block changed')
                return
            if target.get('mode') == 'dropdown':
                self.arm_dropdown(target, original, panel_box, full_image.size, question_rect, rect, window, desktop, panel_anchor)
                return
            if target.get('mode') == 'multiple':
                self.choice_queue = dict(choices=target['choices'], index=0, original=original,
                    panel_box=panel_box, image_size=full_image.size, question_rect=question_rect,
                    rect=rect, window=window, desktop=desktop, anchor=panel_anchor,
                    deadline=time.monotonic()+120)
                self.advance_choices(start)
                return
            if target.get('mode') == 'text':
                self.arm_text_answer(target, original, panel_box, full_image.size, question_rect, rect, window, desktop, panel_anchor)
                return
            try:
                answer_point, control_pixel = choice_position(original, target, question_rect)
            except ValueError as exc:
                logging.warning('CHOICE REJECTED: %s; cursor not moved', exc)
                return
            logging.info('CHOICE CONTROL: option %s/%s; detected center=%s', target['choice_index'], target['choice_count'], answer_point)
            logging.info('CHOICE COORDS: normalized=(%.5f, %.5f); panel=%s; start=%s; target=%s',
                         target['x'], target['y'], question_rect, start, answer_point)
            try:
                diagnostic = original.copy()
                px, py = control_pixel
                draw = ImageDraw.Draw(diagnostic)
                draw.line((0, py, original.width-1, py), fill='red', width=2)
                draw.ellipse((px-7, py-7, px+7, py+7), outline='red', width=2)
                diagnostic.save(log_dir / 'last-choice-target.png')
                (log_dir / 'last-choice-target.json').write_text(json.dumps(
                    dict(target=target, panel=question_rect, start=start, screen_target=answer_point),
                    ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                logging.exception('DIAGNOSTIC: could not save last choice target')
            # Keep the user's horizontal position; indicate only the answer row.
            end = (start[0], answer_point[1])
            if abs(end[1] - start[1]) <= 10:
                # A small vertical round trip confirms a validated answer in-place.
                top, bottom = rect[1], rect[1] + rect[3] - 1
                pulse_y = start[1] - 8 if start[1] - top >= 8 else min(bottom, start[1] + 8)
                pulse = (start[0], pulse_y)
                logging.info('ALIGNED: answer at current height; short vertical confirmation')
                if self.animate_vertical(start, pulse, 0.20) and self.animate_vertical(pulse, start, 0.20):
                    logging.info('CONFIRMED: answer received at current height; click manually')
                return
            logging.info('MOVE: vertical alignment to answer row; horizontal position unchanged')
            if self.animate_vertical(start, end, 0.8):
                logging.info('FINISHED: vertical alignment complete; click manually')
        except PanelNotFound as exc:
            logging.warning('PANEL: %s', exc)
        except Exception:
            logging.exception('Request failed; cursor remains under user control')
        finally:
            self.busy.release()

    def advance_choices(self, start):
        q = self.choice_queue
        if q is None:
            return False
        try:
            if time.monotonic() > q['deadline'] or bounds() != q['desktop'] or not region_unchanged(q['window'], q['rect'], bounds()):
                raise ValueError('expired or window changed')
            if not contains((q['question_rect'][0], q['question_rect'][1],
                             q['question_rect'][0]+q['question_rect'][2],
                             q['question_rect'][1]+q['question_rect'][3]), *start):
                raise ValueError('cursor outside queued question')
            full = capture(q['rect'])
            if full.size != q['image_size'] or find_question_panel(full, anchor=q['anchor']) != q['panel_box']:
                raise ValueError('panel moved')
            before, after = q['original'].copy(), full.crop(q['panel_box'])
            # Only checkbox marks may change between indications; question text stays checked.
            for target in q['choices']:
                x,y = screen_point(target, (0,0,*before.size))
                rx = max(10, round(12*before.width/q['question_rect'][2]))
                ry = max(10, round(12*before.height/q['question_rect'][3]))
                box = (x-rx,y-ry,x+rx,y+ry)
                ImageDraw.Draw(before).rectangle(box, fill='white')
                ImageDraw.Draw(after).rectangle(box, fill='white')
            if ImageChops.difference(before,after).getbbox() is not None:
                raise ValueError('question content changed outside checkboxes')
        except (ValueError, PanelNotFound) as exc:
            logging.info('MULTI RESET: %s; new analysis required', exc)
            self.choice_queue = None
            return False
        if q['index'] >= len(q['choices']):
            logging.info('MULTI DONE: all %s answers already indicated', len(q['choices']))
            self.signal_text_ready(q['desktop'])
            return True
        target = q['choices'][q['index']]
        end = (start[0], screen_point(target,q['question_rect'])[1])
        logging.info('MULTI: indicating answer %s of %s; select manually, then trigger next', q['index']+1,len(q['choices']))
        if abs(end[1]-start[1]) <= 10:
            top,bottom=q['rect'][1],q['rect'][1]+q['rect'][3]-1
            pulse=(start[0],start[1]-8 if start[1]-top>=8 else min(bottom,start[1]+8))
            done=self.animate_vertical(start,pulse,.2) and self.animate_vertical(pulse,start,.2)
        else:
            done=self.animate_vertical(start,end,.8)
        if done:
            q['index'] += 1
            logging.info('MULTI: %s/%s indicated',q['index'],len(q['choices']))
        return True

    def clear_pending_text(self):
        with self.pending_lock:
            self.pending_text = None
            self.text_click = None

    def arm_text_answer(self, target, original, panel_box, image_size, question_rect, rect, window, desktop, panel_anchor):
        local_field = field_box(target['field'], *original.size)
        fx, fy, fw, fh = panel_screen_rect(local_field, original.size, question_rect)
        expected_field = (fx, fy, fx+fw, fy+fh)
        if fw < 10 or fh < 8:
            logging.warning('TEXT: detected input is too small; request rejected')
            return
        try:
            copy_text(target['answer'])
            logging.info('CLIPBOARD: text answer copied; manual paste is available')
        except Exception:
            logging.exception('CLIPBOARD: could not copy answer')

        def validate(actual_field=None):
            if bounds() != desktop or not region_unchanged(window, rect, bounds()):
                logging.info('TEXT VALIDATION: window geometry changed')
                return False
            current_full = capture(rect)
            if current_full.size != image_size or find_question_panel(current_full, anchor=panel_anchor) != panel_box:
                logging.info('TEXT VALIDATION: question panel moved')
                return False
            mask_field = target['field']
            if actual_field is not None:
                # UI Automation has already verified this is the clicked, empty edit.
                # Mask its real focus outline, not an approximate model rectangle.
                qx, qy, qw, qh = question_rect
                l, t, r, b = actual_field
                if not (qx <= l < r <= qx+qw and qy <= t < b <= qy+qh):
                    logging.info('TEXT VALIDATION: editable field outside question')
                    return False
                if (r-l)*(b-t)/(qw*qh) > .55:
                    return False
                pad = 7
                mask_field = dict(left=max(0,(l-qx-pad)/qw), top=max(0,(t-qy-pad)/qh),
                                  right=min(1,(r-qx+pad)/qw), bottom=min(1,(b-qy+pad)/qh))
            valid = same_question(original, current_full.crop(panel_box), mask_field)
            if not valid:
                logging.info('TEXT VALIDATION: pixels changed outside verified field')
            return valid

        # Signal before arming: the full 30-second click window starts afterwards.
        if not self.signal_text_ready(desktop):
            logging.info('TEXT: ready indication interrupted; automatic typing not armed')
            return

        with self.pending_lock:
            if self.cancel.is_set():
                return
            self.pending_text = {'text':target['answer'], 'field':expected_field, 'window':window,
                                 'deadline':time.monotonic()+30, 'validate':validate}
        logging.info('TEXT READY: click the empty answer field within 30s to type; clipboard fallback is ready')

    def signal_text_ready(self, desktop):
        start = tuple(self.controller.position)
        top, bottom = desktop[1], desktop[1] + desktop[3] - 1
        up = (start[0], max(top, start[1] - 5))
        down = (start[0], min(bottom, start[1] + 5))
        previous = start
        logging.info('TEXT SIGNAL: short cursor vibration')
        for point in (up, down, up, down, start):
            if not self.animate_vertical(previous, point, 0.07):
                return False
            previous = point
        return True

    def handle_text_click(self, x, y, pressed):
        with self.pending_lock:
            pending = self.pending_text
            if pending is None:
                return False
            if time.monotonic() > pending['deadline']:
                self.pending_text = None
                self.text_click = None
                logging.info('TEXT: click-to-type expired; clipboard unchanged')
                return False
            if not contains(pending['field'], x, y):
                self.pending_text = None
                self.text_click = None
                logging.info('TEXT: click outside answer field; automatic typing cancelled')
                return False
            if pressed:
                self.text_click = (x, y)
                return True
            if self.text_click is None:
                return True
            if not self.busy.acquire(blocking=False):
                self.text_click = None
                logging.info('TEXT: wait for analysis to finish, then click again')
                return True
            self.text_click = None
            self.pending_text = None  # Consume exactly once before starting the worker.
        self.typing_text = True
        try:
            threading.Thread(target=self.enter_text, args=(pending,(x,y)), daemon=True).start()
        except Exception:
            self.typing_text = False
            self.busy.release()
            raise
        return True

    def enter_text(self, pending, click):
        try:
            if time.monotonic() > pending['deadline'] or self.cancel.is_set():
                logging.info('TEXT: pending answer expired or cancelled')
                return
            def validate():
                return time.monotonic() <= pending['deadline'] and pending['validate']()
            result = type_checked(pending['text'], pending['field'], click, pending['window'],
                                  self.cancel, validate, self.typer,
                                  validate_focused=lambda field: time.monotonic() <= pending['deadline'] and pending['validate'](field))
            logging.info('TEXT: %s', result)
        except Exception:
            logging.exception('TEXT: automatic input failed; clipboard remains available')
        finally:
            self.typing_text = False
            self.busy.release()

    def animate_vertical(self, start, end, duration):
        expected = start
        began = time.monotonic()
        while not self.cancel.is_set():
            if tuple(self.controller.position) != expected:
                logging.info('CANCEL: manual movement interrupted indication')
                return False
            fraction = min(1, (time.monotonic() - began) / duration)
            expected = eased_point(start, end, fraction)
            self.controller.position = expected
            if fraction >= 1:
                return True
            self.cancel.wait(0.012)
        logging.info('CANCEL: indication interrupted by input')
        return False

    def run(self):
        try:
            self.listener.start()
            self.keyboard_listener.start()
            logging.info('Started; Right Alt / Mouse 5 / single middle click = analyze; hold middle 2s = exit')
            while not self.quit.wait(0.1):
                if not self.listener.is_alive():
                    raise RuntimeError('Mouse listener stopped')
                if not self.keyboard_listener.is_alive():
                    raise RuntimeError('Keyboard listener stopped')
                if self.middle_down is not None and time.monotonic() - self.middle_down >= 2:
                    self.cancel.set()
                    break
        finally:
            self.cancel.set()
            self.listener.stop()
            self.keyboard_listener.stop()


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        logging.info('SELF-TEST OK: v19 packaged imports loaded; no input hooks started')
        raise SystemExit(0)
    from single_instance import InstanceLock
    instance = InstanceLock()
    if not instance.acquire():
        logging.info('ALREADY RUNNING: another client instance is active; exiting')
    else:
        try:
            logging.info('VERSION: v19-choice-control-index; PID=%s; aligned tolerance=10px', os.getpid())
            Assistant().run()
        finally:
            instance.close()

