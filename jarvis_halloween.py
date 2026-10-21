"""A synchronized, cancellable 30-second show drawn with actual ASCII characters."""
import math
import time

DURATION = 30.0
GHOST = r"""
    .-''-.
   / o  o \
  |   __   |
  |  (__)  |
  /        \
 / /|    |\ \
 '~ '~~~~' ~'
""".strip('\n').splitlines()
LITTLE_GHOST = r"""
  .--.
 /o o \
 | O  |
 /    \
 '~^^~'
""".strip('\n').splitlines()
PUMPKIN = r"""
           _/|
        .-'  '-.
      .'  .--.  '.
     /   /    \   \
    |   /\    /\   |
    |  /__\  /__\  |
    |       ^      |
    |  \  \___/ /  |
     \  '------'  /
      '._      _.'
         '----'
""".strip('\n').splitlines()
HOUSE = r"""
           /\
      /\  /  \  /\
     /  \/ /\ \/  \
    /____\/__\/____\
    | [] | [] | [] |
    |    |    |    |
    | [] | /\ | [] |
    |____|_||_|____|
""".strip('\n').splitlines()
TREE = r"""
   \    /   /
    \  /___/
  ___\|   /
      |__/___
   ___| /
      ||
      ||
    __||__
""".strip('\n').splitlines()
BOO = r"""
 BBBBB    OOOOO    OOOOO    !!
 BB  BB  OO   OO  OO   OO   !!
 BBBBB   OO   OO  OO   OO   !!
 BB  BB  OO   OO  OO   OO
 BBBBB    OOOOO    OOOOO    !!
""".strip('\n').splitlines()
BATS = [r' /\                 /\ ', r"/  \___/\_____/\___/  "]


def active(data, now=None):
    if data.get('show') != 'halloween' or data.get('result') != 'running' or data.get('attention'):
        return False
    try:
        age = (time.time() if now is None else now) - float(data['show_started'])
        return math.isfinite(age) and 0 <= age < DURATION
    except (KeyError, TypeError, ValueError):
        return False


class Canvas:
    def __init__(self, width, height):
        self.w, self.h = max(1, width-1), max(1, height-1)
        self.grid = [[(' ', 0) for _ in range(self.w)] for _ in range(self.h)]

    def text(self, x, y, text, color):
        y = int(y)
        if not 0 <= y < self.h:
            return
        for offset, character in enumerate(text):
            at = int(x)+offset
            if 0 <= at < self.w:
                self.grid[y][at] = character, color

    def sprite(self, x, y, lines, color):
        for row, line in enumerate(lines):
            for col, char in enumerate(line):
                if char != ' ':
                    self.text(int(x)+col, int(y)+row, char, color)

    def center(self, y, text, color):
        self.text(max(0, (self.w-len(text))//2), y, text, color)

    def output(self):
        result = []
        for row, values in enumerate(self.grid):
            col = 0
            while col < self.w:
                char, color = values[col]
                if char == ' ' and color == 0:
                    col += 1
                    continue
                end = col+1
                while end < self.w and values[end][1] == color:
                    end += 1
                text = ''.join(char for char, _ in values[col:end]).rstrip()
                if text:
                    result.append((row, col, text, color, self.w-col))
                col = end
        return result


def frame(width, height, elapsed):
    t = max(0., min(DURATION, elapsed))
    c = Canvas(width, height)
    w, h = c.w, c.h
    if t < 4:
        chapter = 'SOMETHING SPOOKY IS COMING...'
    elif t < 12:
        chapter = 'THE HAUNTING HAS BEGUN'
    elif t < 22:
        chapter = 'GHOST PARADE - PLEASE KEEP YOUR CIRCUITS INSIDE'
    elif t < 27:
        chapter = 'BOO!  EVEN THE GHOSTS HAVE GOOD TIMING.'
    else:
        chapter = 'HAPPY HALLOWEEN, SIR.  ALL SCARES COMPLETE.'
    # Stars twinkle locally; the background never flashes as a whole.
    for i in range(max(10, w*h//100)):
        x, y = (i*37+11) % w, 3+(i*17+5) % max(1, h-8)
        char = '+' if (int(t*2)+i)%7 == 0 else '.'
        c.text(x, y, char, 8 if (i+int(t))%5 == 0 else 9)
    moon = [' .-----.', '/  _    \\', '| (_)   |', '\\      /', " '----'"]
    c.sprite(w-13, 3, moon, 7)
    # Several bats cross independently with alternating wing silhouettes.
    for i in range(3 if w >= 85 else 2):
        x = ((t*(7+i*2)+i*w/3) % (w+24))-24
        y = 4+i*2+math.sin(t*2+i)
        wings = [r' /\__/\ ', r' \    / ', r'  \../  '] if int(t*6+i)%2 else [r' _    _ ', r'/ \/\/ \ ', r'   \/   ']
        c.sprite(x, y, wings, 8)
    ground = h-6
    if w >= 72 and h >= 27:
        c.sprite(3, ground-len(HOUSE), HOUSE, 9)
        for i in range(3):
            c.text(7+i*5, ground-4, '[]', 10 if (int(t*2)+i)%4 else 11)
        c.sprite(w-20, ground-len(TREE), TREE, 9)
        c.text(1, ground, '_'*(w-2), 9)
        for i in range(8):
            c.text((i*29+t*(2+i%3))%w, 6+(i*7+t*(1+i%2))%max(1, ground-7), '*', 10)
    if w >= 43 and h >= 22:
        pumpkin_x = w/2-11+math.sin(t*1.3)*min(9, w/12)
        pumpkin_y = max(5, ground-len(PUMPKIN)-abs(math.sin(t*2.5))*2)
        pumpkin = PUMPKIN[:]
        if int(t*2)%7 == 0:
            pumpkin[4] = '    |   --    /\\   |'
        c.sprite(pumpkin_x, pumpkin_y, pumpkin, 10)
        c.text(pumpkin_x+12, pumpkin_y+6, '^', 11)
    # A large ghost floats across the scene; small ghosts form a later parade.
    ghost_x = (w+16)-(t*5.5 % (w+32))
    ghost_y = max(4, min(h-13, 8+math.sin(t*1.2)*3))
    if h >= 20:
        c.sprite(ghost_x, ghost_y, GHOST, 7)
    count = 6 if 12 <= t < 22 else 3
    for i in range(count):
        x = (t*(3+i%2)+i*(w+10)/count)%(w+10)-8
        y = max(4, min(h-11, h/2+math.sin(t*1.7+i)*3))
        ghost = LITTLE_GHOST if int(t*3+i)%9 else [line.replace('o o', '^ ^') for line in LITTLE_GHOST]
        c.sprite(x, y, ghost, 7 if i%2 else 8)
    if 22 <= t < 27 and w >= 38 and h >= 18:
        c.sprite((w-31)//2+round(math.sin(t*5)), max(4, h//2-5), BOO, 10)
    if t >= 27:
        c.center(max(4, h//2-4), '<<< HAPPY HALLOWEEN >>>', 10)
        c.center(max(5, h//2-2), 'J A R V I S   A F T E R   D A R K', 8)
    c.text(0, 0, ' '*w, 0)
    c.center(0, 'J A R V I S  /  HALLOWEEN AFTER DARK', 10)
    c.text(0, 1, '='*w, 8)
    for row in range(max(2, h-5), h):
        c.text(0, row, ' '*w, 0)
    c.center(h-5, chapter[:w], 8 if t < 22 else 10)
    progress_width = max(4, min(50, w-24))
    fill = min(progress_width, int(t/DURATION*progress_width))
    c.center(h-3, f'[{"#"*fill}{"-"*(progress_width-fill)}]  {int(t):02d}/30s', 10)
    c.center(h-2, 'R reset / cancel show   |   Q close this view', 3)
    return c.output()


def run_show():
    from jarvis_status import emit
    from jarvis_reset import generation
    token = generation()
    started = time.time()
    deadline = time.monotonic()+DURATION
    emit('action', 'Playing the 30-second Halloween ASCII show.', result='running',
         show='halloween', show_started=str(started), show_duration=str(DURATION),
         activity_caption='Halloween ASCII show', activity_step='show', model_pending='0')
    try:
        while time.monotonic() < deadline:
            if generation() != token:
                return False
            time.sleep(min(.05, max(0, deadline-time.monotonic())))
        return True
    finally:
        emit(show='', show_started='', show_duration='')
