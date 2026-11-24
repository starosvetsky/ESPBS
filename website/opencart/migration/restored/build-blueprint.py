"""Deterministic hand-built geometry. No tracing, raster content or dependencies."""
from pathlib import Path
from math import sqrt

ROOT = Path(__file__).parent
parts = []

def add(s): parts.append(s)
def path(d, cls='bp-detail', extra=''):
    add(f'<path class="{cls}" d="{d}" {extra}/>')
def rect(x,y,w,h,cls='bp-detail'):
    path(f'M{x} {y}h{w}v{h}h{-w}Z',cls)
def group(id, cls='', transform=''):
    add(f'<g id="bp-{id}" class="{cls}"'+(f' transform="{transform}"' if transform else '')+'>')
def end(): add('</g>')
def point(x,y): return f'{x:.3f} {y:.3f}'

add('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 580 430" width="580" height="430" class="cabinet-blueprint" data-blueprint="" role="img" aria-labelledby="bp-title bp-description" fill="none" stroke="#c8e1f5" stroke-width=".9" stroke-linecap="round" stroke-linejoin="round">
<title id="bp-title">Телекоммуникационные шкафы — инженерный чертёж</title>
<desc id="bp-description">Два изометрических шкафа разного размера: коммутационные панели, монтажные стойки, вентиляционные прорези и размерные направляющие. Условная иллюстрация, не монтажная схема.</desc>
<style>
.cabinet-blueprint .bp-edge{stroke:#e1effb;stroke-width:1.05}
.cabinet-blueprint .bp-guide{stroke:#aacce9;stroke-width:.7;stroke-dasharray:2 8;opacity:.24}
.cabinet-blueprint .bp-guide-cross{stroke-width:.7;opacity:.38}
.cabinet-blueprint .bp-door{stroke:#d3e8f8;stroke-width:.95}
.cabinet-blueprint .bp-detail{stroke-width:.7;opacity:.75}
.cabinet-blueprint .bp-door-seal,.cabinet-blueprint .bp-rail-mark{stroke-width:.55;opacity:.55}
.cabinet-blueprint .bp-module-case{stroke-width:.85;opacity:.9}
.cabinet-blueprint .bp-fastener{stroke-width:.65;opacity:.6}
.cabinet-blueprint .bp-handle{stroke-width:1.2}
.cabinet-blueprint .bp-dimensions,.cabinet-blueprint .bp-annotations{stroke-width:.65;opacity:.55}
.cabinet-blueprint .bp-led{fill:#d4eefa;stroke:none}
</style>
<g id="bp-background"><path fill="#0b54a0" stroke="none" d="M0 0H580V430H0Z"/></g>''')
group('construction-guides','bp-guides')
for d in ['M28 354H554','M57 391V43','M544 368V69','M26 327 520 42','M61 411 550 129','M107 380 534 133']:
    path(d,'bp-guide')
for x,y in [(57,354),(544,354),(106,281)]:
    path(f'M{x-4} {y}h8m-4-4v8','bp-guide-cross')
end()

def cabinet(name,x,y,w,h,depth):
    u=sqrt(3)/2
    a=(x,y); b=(x+u*w,y-w/2); c=(b[0]-u*depth,b[1]-depth/2); d=(x-u*depth,y-depth/2)
    lower=lambda p:(p[0],p[1]+h)
    group(name,f'bp-cabinet bp-{name}')
    group(name+'-surfaces','bp-surfaces')
    for pts,color in [([a,b,c,d],'#ffffff06'),([a,d,lower(d),lower(a)],'#001a3518'),([a,b,lower(b),lower(a)],'#ffffff03')]:
        add('<polygon points="'+' '.join(point(*p) for p in pts)+f'" fill="{color}" stroke="none"/>')
    end()
    group(name+'-structure','bp-structure')
    # Twelve shared edges are represented once; every segment is parallel to
    # one of the three basis vectors (sqrt(3)/2, ±1/2), (0,1).
    for i,(p,q) in enumerate([(d,c),(c,b),(b,a),(a,d),(d,lower(d)),(a,lower(a)),(b,lower(b)),(lower(d),lower(a)),(lower(a),lower(b))]):
        path('M'+point(*p)+' '+point(*q),'bp-edge',f'pathLength="1" style="--edge-order:{i}"')
    end()
    # Front-local coordinates: horizontal rack width projects at -30 degrees.
    group(name+'-panels','bp-panels',f'matrix({u:.8f} -.5 0 1 {x} {y})')
    rect(9,9,w-18,h-18,'bp-door')
    rect(15,15,w-30,h-30,'bp-detail bp-door-seal')
    # Offset sill aligns with both front and depth directions.
    path(f'M0 {h+7}h{w}v-7M0 {h}v7','bp-detail')
    for cx in [20,w-20]:
        for cy in [20,h-20]:
            add(f'<circle class="bp-fastener" cx="{cx}" cy="{cy}" r="1.5"/>')
    for cy in ([38,100,166] if name=='large-cabinet' else [30,79]):
        path(f'M{w-10} {cy}h3v9h-3','bp-detail')
    path(f'M12 {h*.53}v15m-2-13h4','bp-handle')
    end()
    group(name+'-modules','bp-modules',f'matrix({u:.8f} -.5 0 1 {x} {y})')
    if name=='large-cabinet':
        # Rack mounting rails and neutral patch/switch trays.
        path(f'M29 28v{h-56}M{w-29} 28v{h-56}','bp-detail')
        for yy in range(32,h-30,12):
            path(f'M25 {yy}h3m{w-56} 0h3','bp-rail-mark')
        for row,yy in enumerate([31,64,97,130,163]):
            group(f'patch-panel-{row+1}')
            rect(33,yy,w-66,23,'bp-module-case')
            # Four sockets per tray; open slots, no invented brand/specification.
            for xx in [42,61,80,99]:
                rect(xx,yy+7,12,8)
                path(f'M{xx+3} {yy+15}v2h6v-2','bp-rail-mark')
            for xx in [36,w-36]:
                add(f'<circle class="bp-fastener" cx="{xx}" cy="{yy+11.5}" r="1.1"/>')
            path(f'M117 {yy+6}h8m-8 4h8m-8 4h8','bp-rail-mark')
            end()
    else:
        for yy in [27,62]:
            rect(24,yy,w-48,25,'bp-module-case')
            for offset in [7,12,17]: path(f'M30 {yy+offset}h{w-60}','bp-detail')
            for xx in [27,w-27]:
                add(f'<circle class="bp-fastener" cx="{xx}" cy="{yy+3}" r=".9"/>')
    end()
    # Side-local width runs into depth (-30 degrees from left horizontal).
    group(name+'-ventilation','bp-ventilation',f'matrix({-u:.8f} -.5 0 1 {x} {y})')
    rect(9,9,depth-18,h-18,'bp-detail')
    for yy in ([30,67,104,141,178] if name=='large-cabinet' else [27,65]):
        for xx in [20,26,32]: path(f'M{xx} {yy}v17','bp-detail')
    path(f'M0 {h+7}h{depth}v-7M{depth} {h}H0','bp-detail')
    end()
    group(name+'-indicators','bp-indicators',f'matrix({u:.8f} -.5 0 1 {x} {y})')
    for i,yy in enumerate([42,108,174] if name=='large-cabinet' else [34,69]):
        add(f'<circle cx="{w-39}" cy="{yy}" r="1.8" class="bp-led"/>')
    end()
    end()

cabinet('large-cabinet',174,180,170,208,80)
cabinet('small-cabinet',427,242,96,112,60)
group('dimensions','bp-dimensions')
for d in ['M74 140V348','M68 144l12-7','M68 352l12-7','M89 140h-15','M89 348h-15',
          'M99 104 246 19','M94 99l10 10','M241 14l10 10','M111 127l-12-23','M258 42l-12-23',
          'M535 194V306','M530 197l10-6','M530 309l10-6','M518 194h17','M518 306h17']:
    path(d,'bp-dimension-line')
end()
group('technical-details','bp-annotations')
path('M293 354 333 377H391','bp-callout')
add('<circle class="bp-callout" cx="289" cy="352" r="4"/>')
path('M41 77H108l24 24M393 137v-13h42','bp-callout')
end()
add('</svg>')
svg='\n'.join(parts)+'\n'
(ROOT/'assets/footer-engineering.svg').write_text(svg,encoding='utf-8')
(ROOT/'blueprint.twig').write_text(svg,encoding='utf-8')
print('Generated SVG and inline Twig from identical hand-built geometry.')
