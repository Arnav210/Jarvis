"""SKYFALL: a deterministic real-time 3D ASCII Iron Man short film."""
from __future__ import annotations

if __package__ in (None, ''):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
from functools import lru_cache
import math
import re
import time
from jarvis.ui.jarvis_score import story_time, IMPACTS, elapsed as score_elapsed

DURATION = 54.0
FPS = 18
RAMP = '.,:;irsXA253hMHGS#9B&@'
SHOTS = ((0, 'IGNITION'), (7, 'CITY PURSUIT'), (16, 'SURROUNDED'),
         (28, 'ARC REACTOR / CHARGING'), (35, 'REPULSOR COMEBACK'), (47, 'CLEAR SKIES'))
HITS = tuple(story_time(second) for second in IMPACTS)
ACTS = ((0, 'I / PURSUIT'), (16, 'II / SURROUNDED'), (35, 'III / COMEBACK'))


def cinematic_time(seconds):
    """Slow the final wind-up, then catch up before the score-aligned damage cue."""
    t = story_time(seconds)
    start, end = HITS[-2]+.08, HITS[-1]-.8
    if start < t < end:
        u = (t-start)/(end-start)
        # First 65% moves at one quarter speed; the release catches up continuously.
        mapped = u*.25 if u <= .65 else .1625+(u-.65)*(.8375/.35)
        return start+(end-start)*mapped
    return t


def add(a, b): return tuple(x + y for x, y in zip(a, b))
def sub(a, b): return tuple(x - y for x, y in zip(a, b))
def mul(a, k): return tuple(x * k for x in a)
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def length(a): return math.sqrt(dot(a, a))
def unit(a): return mul(a, 1/max(.000001, length(a)))
def clamp(x, lo=0., hi=1.): return max(lo, min(hi, x))
def ease(x): x = clamp(x); return x*x*(3-2*x)
def mix(a, b, t): return add(a, mul(sub(b, a), t))


def noise(n):
    return (math.sin(n * 127.1 + 311.7) * 43758.5453) % 1


def rotate(p, pitch=0., yaw=0., roll=0.):
    x, y, z = p
    c, s = math.cos(pitch), math.sin(pitch)
    y, z = y*c-z*s, y*s+z*c
    c, s = math.cos(yaw), math.sin(yaw)
    x, z = x*c+z*s, -x*s+z*c
    c, s = math.cos(roll), math.sin(roll)
    return x*c-y*s, x*s+y*c, z


class Camera:
    def __init__(self, eye, target, width, height, roll=0., zoom=1.):
        self.eye = eye
        self.forward = unit(sub(target, eye))
        self.right = unit(cross(self.forward, (0, 1, 0)))
        self.up = unit(cross(self.right, self.forward))
        if roll:
            r, u = self.right, self.up
            self.right = add(mul(r, math.cos(roll)), mul(u, math.sin(roll)))
            self.up = sub(mul(u, math.cos(roll)), mul(r, math.sin(roll)))
        self.cx, self.cy = width*.5, height*.51
        self.fy = height * 1.05 * zoom
        self.fx = self.fy * 2
        self.cache = {}

    def local(self, p):
        cached = self.cache.get(p)
        if cached is not None:
            return cached
        v = sub(p, self.eye)
        result = dot(v, self.right), dot(v, self.up), dot(v, self.forward)
        self.cache[p] = result
        return result

    def project(self, p):
        x, y, z = p
        if z < .24999:
            return None
        return self.cx + self.fx*x/z, self.cy - self.fy*y/z, 1/z


class Film:
    """Flat-shaded triangle rasterizer with near clipping and reciprocal-depth occlusion."""
    def __init__(self, width, height, camera):
        self.w, self.h = max(1, width-1), max(1, height-1)
        self.camera = camera
        self.grid = [[' ']*self.w for _ in range(self.h)]
        self.color = [[0]*self.w for _ in range(self.h)]
        self.depth = [[0.]*self.w for _ in range(self.h)]
        self.light = unit((-.4, .85, .6))

    def pixel(self, x, y, depth, char, color):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 2 <= y < self.h-3 and depth >= self.depth[y][x]:
            self.depth[y][x] = depth
            self.grid[y][x], self.color[y][x] = char, color

    def text(self, x, y, text, color=1):
        y = int(y)
        if 0 <= y < self.h:
            for i, char in enumerate(text):
                at = int(x)+i
                if 0 <= at < self.w:
                    self.grid[y][at], self.color[y][at] = char, color

    def centered(self, y, text, color=1):
        self.text(max(0, (self.w-len(text))//2), y, text[:self.w], color)

    def point(self, world, color=1, char='*', radius=0):
        projected = self.camera.project(self.camera.local(world))
        if projected:
            x, y, inv = projected
            for dy in range(-radius, radius+1):
                for dx in range(-radius*2, radius*2+1):
                    if not radius or dx*dx/4+dy*dy <= radius*radius:
                        self.pixel(x+dx, y+dy, inv, char, color)

    def line(self, a, b, color=1, char='-', thickness=0):
        a, b = self.camera.local(a), self.camera.local(b)
        if a[2] < .25 and b[2] < .25:
            return
        if a[2] < .25: a = mix(a, b, (.25-a[2])/(b[2]-a[2]))
        if b[2] < .25: b = mix(b, a, (.25-b[2])/(a[2]-b[2]))
        a, b = self.camera.project(a), self.camera.project(b)
        if not a or not b:
            return
        steps = min(500, max(1, int(max(abs(b[0]-a[0]), abs(b[1]-a[1])))))
        for i in range(steps+1):
            t = i/steps
            x, y, inv = (a[j]+(b[j]-a[j])*t for j in range(3))
            self.pixel(x, y, inv, char, color)
            if thickness:
                self.pixel(x+1, y, inv, char, color)

    def triangle(self, a, b, c, color, emission=0.):
        vertices = [self.camera.local(p) for p in (a, b, c)]
        if all(p[2] < .25 for p in vertices):
            return
        normal = unit(cross(sub(b, a), sub(c, a)))
        middle = mul(add(add(a, b), c), 1/3)
        view = unit(sub(self.camera.eye, middle))
        half = unit(add(self.light, view))
        diffuse = abs(dot(normal, self.light))
        specular = max(0, abs(dot(normal, half)))**22
        intensity = clamp(.14 + .63*diffuse + .4*specular + emission)
        distance = length(sub(middle, self.camera.eye))
        intensity *= max(.20, 1-distance/230)
        if distance > 95 and not emission: color = 15
        if specular > .85 and color in {12, 13}: color = 7
        char = RAMP[min(len(RAMP)-1, int(intensity*(len(RAMP)-1)))]
        if color == 15:
            char = '  .,:-'[min(5,int(intensity*5))]
        clipped = []
        for i, current in enumerate(vertices):
            previous = vertices[i-1]
            if (current[2] >= .25) != (previous[2] >= .25):
                clipped.append(mix(previous, current, (.25-previous[2])/(current[2]-previous[2])))
            if current[2] >= .25: clipped.append(current)
        if len(clipped) < 3:
            return
        projected = [self.camera.project(p) for p in clipped]
        for i in range(1, len(projected)-1):
            self.raster(projected[0], projected[i], projected[i+1], color, char)

    def raster(self, a, b, c, color, char):
        x0, y0, z0 = a; x1, y1, z1 = b; x2, y2, z2 = c
        denominator = (y1-y2)*(x0-x2)+(x2-x1)*(y0-y2)
        if abs(denominator) < .01:
            return
        left = max(0, math.floor(min(x0, x1, x2)))
        right = min(self.w-1, math.ceil(max(x0, x1, x2)))
        top = max(2, math.floor(min(y0, y1, y2)))
        bottom = min(self.h-4, math.ceil(max(y0, y1, y2)))
        if left > right or top > bottom:
            return
        inv = 1/denominator
        for y in range(top, bottom+1):
            yy = y+.5
            grid, colors, depths = self.grid[y], self.color[y], self.depth[y]
            for x in range(left, right+1):
                xx = x+.5
                w0 = ((y1-y2)*(xx-x2)+(x2-x1)*(yy-y2))*inv
                w1 = ((y2-y0)*(xx-x2)+(x0-x2)*(yy-y2))*inv
                if w0 >= -.001 and w1 >= -.001 and w0+w1 <= 1.001:
                    depth = w0*z0+w1*z1+(1-w0-w1)*z2
                    if depth > depths[x]:
                        depths[x], grid[x], colors[x] = depth, char, color

    def output(self):
        result = []
        for y in range(self.h):
            x = 0
            while x < self.w:
                color = self.color[y][x]
                end = x+1
                while end < self.w and self.color[y][end] == color: end += 1
                text = ''.join(self.grid[y][x:end])
                if text.strip(): result.append((y, x, text, color, end-x))
                x = end
        return result


class Mesh:
    def __init__(self): self.faces = []

    def poly(self, points, color, emission=0.):
        for i in range(1, len(points)-1):
            self.faces.append((points[0], points[i], points[i+1], color, emission))

    def box(self, center, size, color):
        x, y, z = center; a, b, c = (n/2 for n in size)
        p = [(x+dx*a, y+dy*b, z+dz*c) for dx, dy, dz in
             [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
        for face in [(0,3,2,1),(4,5,6,7),(0,4,7,3),(1,2,6,5),(0,1,5,4),(3,7,6,2)]:
            self.poly([p[i] for i in face], color)

    def orb(self, center, scale, color, rings=4, slices=8, emission=0.):
        for j in range(rings):
            for i in range(slices):
                points = []
                for a, b in [(j,i),(j,i+1),(j+1,i+1),(j+1,i)]:
                    lat = -math.pi/2 + math.pi*a/rings
                    lon = math.tau*b/slices
                    points.append(add(center, (scale[0]*math.cos(lat)*math.cos(lon), scale[1]*math.sin(lat), scale[2]*math.cos(lat)*math.sin(lon))))
                self.poly(points, color, emission)

    def bone(self, a, b, r1, r2, color, sides=6):
        direction = unit(sub(b, a))
        basis = unit(cross(direction, (0,0,1) if abs(direction[2]) < .9 else (0,1,0)))
        other = cross(direction, basis)
        rings = []
        for center, radius in [(a,r1),(b,r2)]:
            rings.append([add(center, add(mul(basis, radius*math.cos(i*math.tau/sides)), mul(other, radius*math.sin(i*math.tau/sides)))) for i in range(sides)])
        self.poly(rings[0], color); self.poly(list(reversed(rings[1])), color)
        for i in range(sides):
            n = (i+1)%sides
            self.poly([rings[0][i],rings[0][n],rings[1][n],rings[1][i]], color)

    def draw(self, film, transform=lambda p:p):
        transformed = {}
        for a, b, c, color, emission in self.faces:
            for point in (a, b, c):
                if point not in transformed:
                    transformed[point] = transform(point)
            film.triangle(transformed[a], transformed[b], transformed[c], color, emission)


@lru_cache(maxsize=1)
def _armor_shell():
    """Faceted red/gold armor with rigged limbs, mask, eye slits and chest core."""
    m = Mesh()
    m.orb((0,1.05,0), (.67,.86,.40), 12, 4, 8)
    m.bone((0,.65,0),(0,-.05,0),.43,.35,14)
    m.orb((0,-.03,0),(.47,.29,.31),12,3,8)
    for side in [-1,1]:
        m.poly([(side*.05,1.48,.38),(side*.53,1.45,.26),(side*.46,.98,.39),(side*.12,1.04,.47)],13)
        m.poly([(side*.10,.82,.38),(side*.41,.82,.29),(side*.30,.28,.30),(side*.10,.36,.39)],12)
    m.bone((0,1.65,0),(0,1.93,0),.22,.22,14)
    m.orb((0,2.20,0),(.39,.49,.36),12,4,8)
    # Faceplate is deliberately planar so its eye slits stay crisp in close-up.
    m.poly([(-.27,2.51,.39),(.27,2.51,.39),(.34,2.20,.43),(.21,1.89,.39),(-.21,1.89,.39),(-.34,2.20,.43)],13)
    for side in [-1,1]:
        m.poly([(side*.055,2.29,.452),(side*.28,2.34,.452),(side*.28,2.26,.452),(side*.065,2.24,.452)],1,1)
    m.poly([(-.16,1.98,.443),(.16,1.98,.443),(.12,1.94,.443),(-.12,1.94,.443)],14)
    m.orb((0,1.16,.405),(.145,.145,.055),1,3,10,1)
    m.poly([(-.085,1.22,.465),(.085,1.22,.465),(0,1.075,.465)],7,1)
    return m


def armor(t, firing=False):
    m = Mesh()
    m.faces = list(_armor_shell().faces)
    hands, boots = [], []
    for side in [-1,1]:
        shoulder = (side*.70,1.50,0)
        elbow = mix((side*1.02,.78,-.10+math.sin(t*2+side)*.06),(side*.91,1.13,.63),float(firing))
        hand = mix((side*1.15,.22,.12),(side*.82,1.20,1.46),float(firing))
        m.orb(shoulder,(.32,.32,.32),12,3,6)
        m.bone(shoulder,elbow,.22,.16,13)
        m.orb(elbow,(.18,.18,.18),14,3,6)
        m.bone(elbow,hand,.25,.17,12)
        m.orb(hand,(.20,.19,.20),12,3,6)
        m.orb(add(hand,(0,0,.17)),(.09,.09,.04),1,2,6,1)
        hip = (side*.27,-.10,0)
        knee = (side*.32,-.90,.10+math.sin(t*1.8+side)*.10)
        boot = (side*.38,-1.63,.06)
        m.bone(hip,knee,.27,.19,13)
        m.orb(knee,(.24,.23,.23),12,3,6)
        m.bone(knee,boot,.27,.18,12)
        m.box(add(boot,(0,-.08,.13)),(.40,.30,.64),12)
        m.orb(add(boot,(0,-.22,0)),(.14,.045,.16),1,2,6,1)
        hands.append(hand); boots.append(add(boot,(0,-.24,0)))
    return m, hands, boots


def drone(t, index):
    m = Mesh()
    m.orb((0,0,0),(.75,.46,.56),3,3,6)
    for side in [-1,1]:
        wing = [(side*.4,0,.25),(side*1.85,.12,-.25),(side*1.4,-.12,-.65),(side*.4,-.24,-.22)]
        m.poly(wing,14)
        m.poly([add(p,(0,.12,0)) for p in wing],3)
        m.bone((side*.75,0,-.1),(side*1.3,.25,-.50),.12,.22,14)
    m.orb((0,.04,.54),(.32,.10,.06),12,2,6,1)
    m.orb((0,0,-.50),(.18,.18,.10),4,2,6,1)
    return m


def flight_z(t):
    if t < 16: return t*9-36
    if t < 24:
        u=t-16
        return 108+9*(u-u*u/16)
    if t < 35: return 144.
    u=t-35
    return 144+9*(u*u/6 if u<3 else u-1.5)


def hero_pose(t):
    if t < 7:
        return (0,-2.2+15*ease(t/7),t*t*.55), .4*ease(t/7), math.sin(t*.7)*.08, math.sin(t)*.06
    if t < 16:
        return (math.sin(t*1.1)*2,13+math.sin(t*.9)*1.2,flight_z(t)), .65, -.18*math.cos(t), -.38*math.sin(t*1.1)
    if t < 28:
        tension=ease((t-16)/8)
        return (math.sin(t*.85)*(4-3*tension),14+math.sin(t*1.4)*(2-1.5*tension),flight_z(t)), .25*(1-tension), .25*math.sin(t), -.62*math.cos(t*.85)*(1-tension)
    if t < 35:
        return (math.sin(t)*.3,15,flight_z(t)), -.06, .08*math.sin(t), .05*math.sin(t*.7)
    if t < 47:
        return (math.sin(t*.45)*2,16+math.sin(t*.8),flight_z(t)), -.12, .20*math.sin(t*.5), .22*math.sin(t)
    return (0,16+(t-47)*.55,flight_z(t)), -.22*ease((t-47)/7), -.15, -.08


def shot(t):
    return max(i for i,(start,_) in enumerate(SHOTS) if t >= start)


def camera_pose(t, hero):
    index = shot(t)
    start = SHOTS[index][0]
    end = SHOTS[index+1][0] if index+1 < len(SHOTS) else DURATION
    u = (t-start)/(end-start)
    target = add(hero,(0,.7,0))
    roll = 0.
    if index == 0:
        offset = (7-4*ease(u),2+u*3,13-2*u)
    elif index == 1:
        # Begin behind the right shoulder, looking down the flight corridor.
        # An eased arc then overtakes the suit before its first counterattack.
        orbit=ease((t-10.6)/2.6)
        theta=2.77+( .65-2.77)*orbit
        radius=9.65+3.35*orbit
        offset=(radius*math.sin(theta),1.8+1.5*orbit,radius*math.cos(theta))
        lock=ease((t-10.6)/.6)
        target=add(hero,(0,.9-.9*math.sin(orbit*math.pi)**2,7*(1-lock)+.5*lock))
        if t>13.2:
            settle=ease((t-13.2)/2.8)
            offset=add(offset,(-3*settle,0,1.7*settle))
        roll=-.045*math.sin(orbit*math.pi)
    elif index == 2:
        # A rising crane reveals the ring of attackers before descending into it.
        theta=.4+ease(u)*2.8
        offset=(21*math.sin(theta),4+10*math.sin(u*math.pi),21*math.cos(theta))
        roll=.045*math.sin(u*math.tau)
    elif index == 3:
        push = ease((u-.15)/.80)
        offset = mix((15,7,19),(.25,1.8,2.8),push)
        target = add(hero,(0,1.0+.6*push,.1))
    elif index == 4:
        if t<37:
            offset=mix((16,8,19),(10,4,15),ease((t-35)/2))
            target=add(hero,(0,1,2))
        else:
            sweep=ease((t-37)/6)
            release=ease((t-43)/3)
            theta=(math.atan2(10,15)*(1-sweep)-.65*sweep)*(1-release)
            radius=(length((10,0,15))*(1-sweep)+15*sweep)-5*release
            offset=(radius*math.sin(theta),4-1.7*sweep-.7*release,radius*math.cos(theta))
            target=add(hero,(0,1,2-1.5*release))
        roll=.035*math.sin(u*math.pi*2)
    else:
        # The camera stops tracking: the suit crosses the foreground, flies past
        # the lens and actually leaves the frame instead of hovering at center.
        anchor=hero_pose(47)[0]
        return add(anchor,(7,3,12)),add(anchor,(0,1.5,0)),0.
    shake = sum(.07*math.exp(-(t-hit)*5)*math.sin((t-hit)*76) for hit in HITS if 0 <= t-hit < .65)
    offset = add(offset,(shake,shake*.6,0))
    return add(hero,offset), target, roll


def drone_flyby(t):
    """A foreground crossing staged relative to the chase lens, with real depth."""
    phase=clamp((t-8.3)/2)
    weight=math.sin(phase*math.pi)**2
    hero=hero_pose(t)[0]
    eye,target,roll=camera_pose(t,hero)
    forward=unit(sub(target,eye))
    right=unit(cross(forward,(0,1,0)))
    up=cross(right,forward)
    crossing=add(eye,add(mul(forward,4+abs(phase-.5)*10),
                        add(mul(right,(phase-.5)*24),mul(up,1.0))))
    return crossing,weight


def enemy_spawn(index):
    return 16. if index>=5 else HITS[index]-6.5


def encirclement(t, index):
    hero=hero_pose(t)[0]
    angle=(index-5)*math.tau/5+(t-16)*.34
    radius=11+17*(1-ease((t-16)/2.5))
    return add(hero,(math.cos(angle)*radius,2.5+math.sin(angle*2)*2,math.sin(angle)*radius))


def enemy_formation(t, index):
    hit = HITS[index]
    hero = hero_pose(t)[0]
    side = -1 if index%2 else 1
    impact_hero=hero_pose(hit)[0]
    impact_eye,_,_=camera_pose(hit,impact_hero)
    forward=unit(sub(impact_hero,impact_eye))
    right=unit(cross(forward,(0,1,0)))
    # Block each attack in world space for its shot, then sweep from depth toward
    # the lens. Attacks and impacts remain readable rather than happening offscreen.
    offset=add(mul(forward,7*(hit-t)-3),mul(right,side*(4.5+index%3*.6)+math.sin(t*1.9+index)*.4))
    base = add(hero,add(offset,(0,1.2+math.cos(t*1.3+index)*1.7,0)))
    # Early hunters close from behind; later pairs fan out to encircle the suit.
    approach = 1-ease((t-(hit-6.5))/2.5)
    base = add(base,add(mul(forward,approach*12),mul(right,side*approach*5)))
    if index >= 5:
        flank = 1-ease((t-(hit-4))/1.2)
        angle = (t-(hit-6.5))*.65
        base = add(base,add(mul(right,side*flank*(5+3*math.sin(angle))),
                            (0,flank*(3+math.cos(angle)),0)))
    # One deliberate lateral break as the targeting sweep reaches this drone.
    dodge = math.sin(math.pi*clamp((t-(hit-2.8))/1.2))**2
    base = add(base,add(mul(right,side*dodge*3.2),(0,dodge*1.1,0)))
    if index>=5:
        departure=ease((t-33)/max(.2,hit-1.5-33))
        return mix(encirclement(t,index),base,departure)
    if index==0 and 8.3<t<10.3:
        crossing,weight=drone_flyby(t)
        return mix(base,crossing,weight)
    return base


def enemy_state(t, index):
    hit = HITS[index]
    if t < enemy_spawn(index): return 'waiting'
    if t >= hit: return 'destroyed'
    if t >= hit-.8: return 'crippled'
    if index>=5 and t<33: return 'encircling'
    if hit-2.8 <= t < hit-1.6: return 'evading'
    if t >= hit-3.6: return 'attacking'
    return 'pursuing' if index < 5 else 'flanking'


def enemy_position(t, index):
    damage = HITS[index]-.8
    if t <= damage: return enemy_formation(t,index)
    # Momentum is captured at damage time: the wreck no longer follows the hero.
    age = min(t,HITS[index])-damage
    origin = enemy_formation(damage,index)
    velocity = mul(sub(enemy_formation(damage,index),enemy_formation(damage-.01,index)),100)
    side = -1 if index%2 else 1
    return add(origin,add(mul(velocity,age),
        (side*.65*math.sin(age*9)*age,-3.5*age*age,.55*math.cos(age*9)*age)))


def enemy_volley(index):
    # Staggered wingmen commit to separate, finite bursts rather than an endless laser.
    hit = HITS[index]
    extra = (20+(index-5)*.24,24+(index-5)*.20,28+(index-5)*.18) if index>=5 else ()
    return (*extra,hit-3.5,hit-1.5)


def enemy_bolt(t, index, launched):
    age = t-launched
    if not 0 <= age < .85: return None
    origin = enemy_formation(launched,index)
    aim = add(hero_pose(launched+.38)[0],(0,.85,0))
    velocity = mul(unit(sub(aim,origin)),length(sub(aim,origin))/.38)
    return add(origin,mul(velocity,max(0,age-.055))),add(origin,mul(velocity,age))


@lru_cache(maxsize=512)
def building(zrow, lane):
    seed = zrow*19+lane*137
    height = 5+noise(seed)*21
    width, depth = 7+noise(seed+1)*5, 9+noise(seed+2)*6
    center = (lane*17,-6+height/2,zrow*20)
    mesh=Mesh();mesh.box(center,(width,height,depth),15)
    return mesh,center,width,height,depth,seed


def skyline(f, t, hero):
    # All architecture is world anchored: dolly/orbit shots produce true parallax.
    level = -6
    ground = Mesh()
    ground.poly([(-95,level,hero[2]-110),(95,level,hero[2]-110),(95,level,hero[2]+130),(-95,level,hero[2]+130)],15)
    ground.draw(f)
    row = math.floor(hero[2]/20)
    for zrow in range(row-5,row+7):
        z = zrow*20
        for lane in [-3,-2,-1,1,2,3]:
            x = lane*17
            mesh,center,width,height,depth,seed=building(zrow,lane)
            cx,cy,cz=f.camera.local(center)
            radius=(width+height+depth)*.5
            if cz+radius<.25 or abs(cx)-radius>(cz+radius)*f.camera.cx/f.camera.fx or abs(cy)-radius>(cz+radius)*f.camera.cy/f.camera.fy:
                continue
            mesh.draw(f)
            if abs(lane) == 1:
                # Thin antennae and independently occluded windows sell city scale.
                f.line((x,level+height,z),(x,level+height+3,z),5,'|')
                for floor in range(2,int(height),3):
                    for column in [-1,0,1]:
                        f.point((x+column*width*.25,level+floor,z+depth/2+.02),13 if noise(seed+floor+column)>.45 else 5,':')
        for x in [-7,7]:
            f.line((x,level+.03,z),(x,level+.03,z+14),1,'-')
        f.line((0,level+.02,z),(0,level+.02,z+8),13,'=')


def exhaust(f, t, transform, boots, power=1.):
    for boot_index, boot in enumerate(boots):
        for i in range(25):
            age = (t*1.8+i*.047)%1
            length = 1.1+4*power
            jitter = .18*age
            local = add(boot,((noise(i+boot_index*31)-.5)*jitter,-age*length,(noise(i+44)-.5)*jitter))
            f.point(transform(local),7 if age<.18 else 1 if age<.65 else 5,'#' if age<.2 else '*' if age<.6 else '.',1 if age<.1 else 0)


def explosion(f, center, age, seed):
    if not 0 <= age < 2.5:
        return
    # Hot core expands into a hollow shock front; shards keep ballistic depth.
    if age < .45:
        mesh = Mesh()
        radius = .2+age*4
        mesh.orb(center,(radius,radius*.75,radius),7 if age<.10 else 10,3,8,.8)
        mesh.draw(f)
    if age < 1.3:
        radius = .3+age*6
        for i in range(28):
            angle = i*math.tau/28
            p = add(center,(math.cos(angle)*radius,math.sin(angle)*radius*.55,math.sin(angle*2)*radius*.12))
            f.point(p,13 if age<.5 else 10,'.' if age>.8 else '+')
    for i in range(40):
        direction = unit((noise(seed+i*3)-.5,noise(seed+i*3+1)-.3,noise(seed+i*3+2)-.5))
        velocity = mul(direction,3+noise(seed+i+53)*7)
        p = add(center,add(mul(velocity,age),(0,-age*age*2,0)))
        tail = sub(p,mul(velocity,.065))
        color = 7 if age<.18 else 13 if age<.65 else 10 if age<1.3 else 15
        f.line(tail,p,color,'*' if age<.6 else '/' if i%2 else '-')
    for i in range(7):
        smoke = add(center,((noise(seed+i)-.5)*age*3,age*(1+i*.15),(noise(seed+i+21)-.5)*age*3))
        f.point(smoke,15,':' if age<1 else '.', min(2,int(age*.8)))


def combat(f, t, transform, hands):
    for index, hit in enumerate(HITS):
        if not enemy_spawn(index) < t < hit+2.5:
            continue
        target = enemy_position(t if t<hit else hit,index)
        damage = hit-.8
        state = enemy_state(t,index)
        if t < hit:
            mesh = drone(t,index)
            heading = sub(hero_pose(t)[0],target)
            bank = .22*math.sin(t*3+index)
            if state == 'evading': bank += (-1 if index%2 else 1)*.85
            age = max(0,t-damage)
            mesh.draw(f,lambda p: add(target,rotate(p,pitch=age*7,
                roll=bank+age*11,yaw=math.atan2(heading[0],heading[2])+age*4)))
            if state == 'crippled':
                # A failing engine sheds sparks and leaves smoke along the wreck's path.
                for n in range(10):
                    trail_age = min(age,n*.055)
                    p = enemy_position(t-trail_age,index)
                    p = add(p,((noise(index*31+n)-.5)*trail_age,trail_age*.8,0))
                    f.point(p,10 if n<3 else 15,'*' if n<3 else ':',0 if n<3 else 1)
                f.point(target,7 if age<.12 else 10,'*',1 if age<.12 else 0)
            for launched in enemy_volley(index):
                bolt = enemy_bolt(t,index,launched)
                if bolt:
                    f.line(*bolt,12,'-',1)
                    if t-launched<.10:f.point(enemy_formation(launched,index),10,'*',1)
            if 0 < damage-t < .44:
                muzzle = transform((0,1.16,.48) if index==len(HITS)-1 else hands[index%2])
                progress = clamp((t-(damage-.44))/.32)
                end = mix(muzzle,target,progress)
                f.line(muzzle,end,1,'=',1)
                f.point(end,7,'@',1)
                f.point(muzzle,7,'*',1)
            # Reticle is attached to the 3D target, never a fixed screen sticker.
            if hit-3.1 < t < damage-.44:
                q=f.camera.project(f.camera.local(target))
                if q and 5<q[0]<f.w-5 and 4<q[1]<f.h-6:
                    f.text(q[0]-4,q[1]-2,'[       ]',12)
                    f.text(q[0]-4,q[1]+2,'[       ]',12)
        else:
            explosion(f,target,t-hit,100+index*97)


def reactor_effects(f,t,transform):
    final_start=HITS[-2]+.08
    final_release=HITS[-1]-.8
    charging = (28<t<35) or (final_start<t<final_release)
    if charging:
        start,end=(28,35) if t<35 else (final_start,final_release)
        power=clamp((t-start)/(end-start))
        core=transform((0,1.16,.51))
        f.point(core,7,'@',1 if power>.45 else 0)
        # Converging energy arcs make the wind-up visible even in the helmet shot.
        for n in range(8):
            angle=n*math.tau/8+t*2
            radius=(.45+(1-power)*1.8)*(1+.10*math.sin(t*17+n))
            outer=transform((math.cos(angle)*radius,1.16+math.sin(angle)*radius,.50))
            inner=transform((math.cos(angle)*radius*.6,1.16+math.sin(angle)*radius*.6,.55))
            f.line(outer,inner,1,'+' if n%2 else '*')
    release=35. if 35<=t<36.1 else final_release
    age=t-release
    if 0<=age<1.1:
        radius=.3+age*17
        previous=None
        for n in range(49):
            angle=n*math.tau/48
            point=transform((math.cos(angle)*radius,1.16+math.sin(angle)*radius*.35,.65+age*3))
            if previous:f.line(previous,point,7 if age<.13 else 1,'=' if age<.4 else '.')
            previous=point
        f.point(transform((0,1.16,.55)),7,'@',1 if age<.25 else 0)


def active(data, now=None):
    if data.get('show') != 'ironman' or data.get('result') != 'running' or data.get('attention'):
        return False
    try:
        age = score_elapsed(data,now) if data.get('show_audio_socket') else (time.time() if now is None else now)-float(data['show_started'])
        return math.isfinite(age) and 0 <= age < DURATION
    except (KeyError, ValueError, TypeError):
        return False


def is_request(text):
    return bool(re.fullmatch(r'(?:hey )?(?:jarvis )?(?:please )?(?:play|start|run|show(?: me)?|activate) '
                            r'(?:the )?(?:iron ?man|skyfall)(?: (?:show|film|movie|animation))?(?: please)?',text))


def frame(width, height, elapsed):
    playback=max(0,min(DURATION-.001,elapsed))
    t = cinematic_time(playback)
    hero, pitch, yaw, roll = hero_pose(t)
    eye, target, camera_roll = camera_pose(t,hero)
    camera = Camera(eye,target,max(1,width-1),max(1,height-1),camera_roll)
    f = Film(width,height,camera)
    for i in range(max(20,min(180,f.w*f.h//35))):
        x = (noise(i+4)*f.w - t*.15*(1+i%3))%f.w
        y = 2+noise(i+310)*max(1,f.h*.43)
        f.pixel(x,y,.00001,'.' if i%5 else '+',15 if i%4 else 5)
    skyline(f,t,hero)
    firing = max([ease((1-(hit-.8-t))/.35) for hit in HITS if 0<hit-.8-t<1.0] or [0.])
    if firing:
        enemy_index=min((i for i,hit in enumerate(HITS) if 0<hit-.8-t<1.0),key=lambda i:HITS[i]-t)
        aim=sub(enemy_position(t,enemy_index),hero)
        aim_yaw=math.atan2(aim[0],aim[2])
        yaw+=((aim_yaw-yaw+math.pi)%math.tau-math.pi)*firing*.65
    mesh,hands,boots = armor(t,firing)
    transform = lambda p:add(hero,rotate(p,pitch,yaw,roll))
    exhaust(f,t,transform,boots,.4 if t<1 else .25 if 24<t<35 else .9 if t<47 else .6)
    mesh.draw(f,transform)
    combat(f,t,transform,hands)
    reactor_effects(f,t,transform)
    if 7<t<24:
        # Foreground vapor streaks occupy a separate, faster parallax layer.
        for i in range(9):
            x = ((i*37.7-t*(23+i*3))%(f.w+35))-25
            y = 3+noise(i+881)*max(1,f.h-8)
            for dx in range(4+i%5): f.pixel(x+dx,y,3.,'-' if dx%2 else '.',15)
    index=shot(t)
    f.text(0,0,' '*f.w,0)
    f.text(1,0,'IRON MAN / SKYFALL',13)
    label=f'{index+1:02d} / {SHOTS[index][1]}'
    if f.w>len(label)+23: f.text(f.w-len(label)-1,0,label,1)
    f.text(0,1,'_'*f.w,5)
    for y in range(max(2,f.h-3),f.h): f.text(0,y,' '*f.w,0)
    if t>49:
        f.centered(f.h-3,'S K Y   C L E A R   /   T H R E A T S   N E U T R A L I Z E D',13)
    else:
        remaining=sum(t<hit for hit in HITS)
        act=max(label for start,label in ACTS if t>=start)
        f.text(1,f.h-3,f'{act}   HOSTILES: {remaining:02d}',3)
        if f.w>98:
            states=[enemy_state(t,i) for i in range(len(HITS))]
            tactic = ('SLOW MOTION / FINAL CHARGE' if HITS[-2]+.08<t<HITS[-1]-.8 else
                      'ARC REACTOR / CHARGING' if 28<t<35 else
                      'ENCIRCLED / INCOMING FIRE' if 'encircling' in states else
                      'DAMAGED / SPIRALING' if 'crippled' in states else
                      'EVASIVE BREAK' if 'evading' in states else
                      'CROSS FIRE' if 'attacking' in states else
                      'FLANKING' if 'flanking' in states else
                      'PURSUIT' if 'pursuing' in states else 'SCANNING')
            f.text(f.w-len(tactic)-2,f.h-3,tactic,12)
    bar=max(1,f.w-17)
    fill=int(bar*playback/DURATION)
    f.text(1,f.h-2,'['+'='*fill+'-'*(bar-fill)+f'] {int(playback):02d}/{int(DURATION)}s',5)
    f.text(1,f.h-1,'R cancel / reset     Q close view',3)
    return f.output()


def run_show(*,soundtrack=True):
    from jarvis.ui.jarvis_status import emit
    from jarvis.computer.jarvis_reset import generation
    from jarvis.ui.jarvis_score import Soundtrack,audio_path
    from jarvis.ui.jarvis_status import runtime
    import signal
    token = generation()
    player=None
    previous=None
    def cancelled(signum,frame):raise KeyboardInterrupt
    try:
        previous=signal.signal(signal.SIGTERM,cancelled)
        if soundtrack and audio_path().is_file():
            player=Soundtrack(audio_path(),runtime())
            player.start()
        emit('action','Playing Iron Man: Skyfall with the Avengers score.' if player else 'Playing Iron Man: Skyfall.',result='running',show='ironman',
             show_started=str(time.time()),show_duration=str(DURATION),
             show_audio_socket=str(player.socket) if player else '',
             activity_caption='Iron Man / Skyfall',activity_step='show',model_pending='0')
        started=time.monotonic()
        deadline=started+DURATION+(3 if player else 0)
        last_position=0.
        while time.monotonic()<deadline:
            if generation()!=token: return False
            if player:
                position=player.position()
                if position is not None:last_position=position
                if position is not None and position>=DURATION-.10:return True
                if player.process.poll() is not None:
                    if last_position>=DURATION-.8 or time.monotonic()-started>=DURATION-.8:return True
                    raise RuntimeError('The soundtrack stopped before the film finished.')
            time.sleep(min(.05,max(0,deadline-time.monotonic())))
        if player:raise RuntimeError('Soundtrack playback timed out.')
        return True
    except KeyboardInterrupt:
        return False
    except (OSError,RuntimeError) as error:
        emit('attention','Soundtrack unavailable: '+str(error),attention='Soundtrack unavailable: '+str(error),result='error')
        return False
    finally:
        if player:player.stop()
        if previous is not None:signal.signal(signal.SIGTERM,previous)
        emit(show='',show_started='',show_duration='',show_audio_socket='')


def main():
    parser=argparse.ArgumentParser(description='Play Iron Man: Skyfall, a 54-second 3D ASCII film with a locally installed score.')
    parser.add_argument('--silent',action='store_true',help='Play the animation without its soundtrack.')
    parser.add_argument('--frame',type=float,help='Print a single still at this second, without starting the show.')
    parser.add_argument('--width',type=int,default=144)
    parser.add_argument('--height',type=int,default=48)
    args=parser.parse_args()
    if args.frame is not None:
        rows=[[' ']*max(1,args.width-1) for _ in range(max(1,args.height-1))]
        for y,x,text,_,_ in frame(args.width,args.height,args.frame):
            rows[y][x:x+len(text)]=text
        print('\n'.join(''.join(row) for row in rows))
        return 0
    from jarvis.ui import jarvis_status as status
    from jarvis.music.jarvis_music_duck import ducked
    import fcntl
    import os
    with (status.runtime()/'runner.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Jarvis is busy. Wait for the current command to finish.')
            return 75
        os.environ['JARVIS_STATUS_FILE']=str(status.runtime()/'state.json')
        (status.runtime()/'state.json').unlink(missing_ok=True)
        status.open_window(force=True)
        with ducked():
            completed=run_show(soundtrack=not args.silent)
        status.emit('complete' if completed else 'cancelled','Skyfall finished.' if completed else 'Skyfall cancelled.',result='0' if completed else 'cancelled')
    return 0 if completed else 130


if __name__=='__main__':
    raise SystemExit(main())
