"""The JARVIS Drone: a decorative visitor that interacts with console artwork."""
import math
import time
import unicodedata

IDLE_DELAY = 45.0
PERIOD = 42.0
LANE_HEIGHT = 8
SPRITE_WIDTH = 18


def idle_age(data, activity, now):
    if activity != 'standby' or data.get('attention') or data.get('result') == 'running' or data.get('mic_active') == '1' or data.get('show'):
        return None
    timestamps = []
    for value in (data.get('_viewer_idle_since'), data.get('updated')):
        try:
            number = float(value)
            if math.isfinite(number):
                timestamps.append(number)
        except (TypeError, ValueError):
            pass
    if not timestamps:
        return None
    elapsed = now-max(timestamps)
    return elapsed-IDLE_DELAY if elapsed >= IDLE_DELAY else None


def occupied_cells(positioned, width, height):
    occupied = set()
    for row, col, text, _, _ in positioned:
        if not 0 <= row < height:
            continue
        for character in text:
            size = 0 if unicodedata.combining(character) else 2 if unicodedata.east_asian_width(character) in {'W', 'F'} else 1
            for offset in range(size):
                if 0 <= col+offset < width:
                    occupied.add((row, col+offset))
            col += size
    return occupied


def find_lane(occupied, width, height):
    best = None
    for y in range(4, height-LANE_HEIGHT-1):
        start = None
        for x in range(width):
            free = x < width-1 and all((row, x) not in occupied for row in range(y, y+LANE_HEIGHT))
            if free and start is None:
                start = x
            if not free and start is not None:
                length = x-start
                if length >= SPRITE_WIDTH+4:
                    score = length+y*.08
                    if best is None or score > best[0]:
                        best = score, start, x, y
                start = None
    return best[1:] if best else None


def ease(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


def overlay(data, positioned, width, height, activity, now=None, scene=None):
    now = time.time() if now is None else now
    age = idle_age(data, activity, now)
    if age is None or width < 30 or height < 18:
        return []
    cycle, phase = int(age//PERIOD), age % PERIOD
    if phase >= 29:
        return []
    occupied = occupied_cells(positioned, width, height)
    scene = scene or {}
    reactor = scene.get('reactor')
    original = {}
    for row, col, text, style, _ in positioned:
        for char in text:
            original[row, col] = (char, style)
            col += 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1
    # Reactor artwork is a playground; its headings, center name and state remain protected.
    if reactor:
        rx, ry, rw, rh = reactor
        for row in range(ry, ry+rh):
            for col in range(rx, rx+rw):
                char = original.get((row, col), (' ', 0))[0]
                if char.isspace() or ry+3 <= row < ry+rh-4 and not char.isalnum():
                    occupied.discard((row, col))
    lane = find_lane(occupied, width, height)
    if lane is None:
        return []
    left, right, top = lane
    routine = ('reactor', 'polish', 'music', 'wave', 'lost')[cycle%5]
    target = left+(right-left-SPRITE_WIDTH)*(.65 if cycle%2 == 0 else .3)
    target_y = top+1+math.sin(age*2)*.8
    if reactor and routine == 'reactor':
        rx, ry, rw, rh = reactor
        angle = max(0, phase-6)*.75
        target = rx+rw/2-7+math.cos(angle)*max(3, rw/2-6)
        target_y = ry+rh/2-3+math.sin(angle)*max(2, rh/2-5)
    elif reactor and routine == 'polish' and scene.get('response'):
        px, py, pw, ph = scene['response']
        target = px+pw+1+math.sin(age*3)
        target_y = py+1+(ph-3)*(.5+.5*math.sin((phase-6)*.5))
    elif reactor and routine == 'music' and scene.get('music'):
        mx, my, mw, mh = scene['music']
        target = mx+mw/2-7+math.sin((phase-6)*.7)*max(2, mw/2-10)
        beat = 3.6 if scene.get('music_playing') else 1.5
        target_y = my-8-abs(math.sin(age*beat))*1.5
    else:
        target += math.sin((phase-6)*.9)*min(6, max(0, (right-left-SPRITE_WIDTH)/5))
    from_left = cycle%2 == 1 if reactor else left < width-right or left == 0
    outside = -SPRITE_WIDTH if from_left else width+1
    entry_y = target_y+math.sin(phase*.8)*2
    if phase < 6:
        x = outside+(target-outside)*ease(phase/6)
        y = entry_y
    elif phase < 22:
        x, y = target, target_y
    else:
        x = target+(outside-target)*ease((phase-22)/7)
        y = target_y-math.sin((phase-22)/7*math.pi)*3
    x, y = int(round(x)), int(round(y))
    eyes = '- -' if int(age*3)%17 == 0 else 'o o'
    if phase >= 18:
        eyes = '^ ^'
    if routine == 'lost' and 6 <= phase < 18:
        eyes = '? ?' if int(phase)%4 < 2 else 'o o'
    antenna = ('    .-^-.' if int(age*4)%3 == 0 else '    .---.')
    lines = [antenna, f' .-[ {eyes} ]-.', "'--[_____]--'", '     / \\']
    decoration = ''
    if 6 <= phase < 18:
        if routine == 'reactor':
            decoration = '   '+'.'*(1+int(phase*3)%5)
        elif routine == 'polish':
            lines[2] += '-*' if int(phase*5)%2 else '--+'
        elif routine == 'wave':
            lines[0] += ' /' if int(phase*3)%2 else ' _'
        elif routine == 'music':
            lines[0] = '  _/ .---. \\_'
            decoration = '   * . *' if int(age*4)%2 else '   . * .'
        else:
            decoration = '      ?'
    painted = {}

    def dot(col, row, char, color):
        if 0 <= row < height-1 and 0 <= col < width-1 and (row, col) not in occupied and char != ' ':
            painted[row, col] = (char, color)

    def put(text, row, color):
        for offset, char in enumerate(text):
            dot(x+offset, int(row), char, color)

    if 6 <= phase < 22 and reactor and routine == 'reactor':
        rx, ry, rw, rh = reactor
        tx, ty = int(rx+rw/2), int(ry+rh/2)
        for step in range(1, 14):
            fraction = step/14
            bx, by = round(x+6+(tx-x-6)*fraction), round(y+2+(ty-y-2)*fraction)
            if (step+int(age*8))%3 != 0:
                dot(bx, by, '.' if step%2 else '+', 8)
        # The ring returns a gentle visual pulse to the drone.
        radius = 3+(phase*2)%6
        for step in range(24):
            angle = step*math.tau/24
            dot(round(tx+math.cos(angle)*radius*2), round(ty+math.sin(angle)*radius), ':', 1)
    if 6 <= phase < 22 and routine in {'polish', 'music'}:
        rect = scene.get('response' if routine == 'polish' else 'music')
        if rect:
            px, py, pw, ph = rect
            brush = int((phase-6)*5)%max(1, pw)
            for offset in range(-2, 3):
                cell = (py, px+brush+offset)
                char = original.get(cell, ('', 0))[0]
                if char in '─┌┐└┘│':
                    painted[cell] = (char, 8 if offset%2 else 1)

    for index, line in enumerate(lines):
        put(line, y+index, 7 if index == 1 else 1)
    put(decoration, y+4, 8)
    put('  JARVIS Drone', y+5, 3)
    put('  '+('~' if int(age*8)%2 else '.')+'   '+('~' if int(age*8)%2 == 0 else '.'), y+4, 5)
    result = []
    for (row, col), (char, color) in sorted(painted.items()):
        if result and result[-1][0] == row and result[-1][1]+len(result[-1][2]) == col and result[-1][3] == color:
            old = result[-1]
            result[-1] = (row, old[1], old[2]+char, color, old[4])
        else:
            result.append((row, col, char, color, width-col-1))
    return result
