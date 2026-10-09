"""Ioffe NSM parameter retrieval with a reviewed, explicitly identified fallback.

Only recognized table fields are parsed. No remote expressions are executed.
Bulk 300 K data are starting values, not concentration-specific transport fits.
"""
import ast
import copy
import datetime
import math
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

BASE='https://www.ioffe.ru/SVA/NSM/Semicond/'
REVIEWED='2026-09-28'
FIELDS=('mass_e_m0','mass_h_m0','mobility_e_cm2_Vs','mobility_h_cm2_Vs','relative_permittivity','intrinsic_cm3')
_CACHE={}

class _Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        elif tag in ('td','th'):self.cell=[]
        elif tag=='sup' and self.cell is not None:self.cell.append('^')
        elif tag=='br' and self.cell is not None:self.cell.append(' | ')
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            if self.row is not None:self.row.append(''.join(self.cell))
            self.cell=None
        elif tag=='tr' and self.row is not None:
            if len(self.row)>=2:self.rows.append(self.row)
            self.row=None
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)

def _number(expression,x=None):
    """Small safe arithmetic evaluator for numeric Ioffe table expressions."""
    expression=expression.strip().replace('−','-').replace('·','*').replace('×','*').replace('^','**')
    expression=re.sub(r'(?<=\d)x', '*x',expression)
    tree=ast.parse(expression,mode='eval')
    if len(list(ast.walk(tree)))>35:raise ValueError('Expression too long.')
    def visit(node):
        if isinstance(node,ast.Expression):return visit(node.body)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):return float(node.value)
        if isinstance(node,ast.Name) and node.id=='x' and x is not None:return x
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            return (-1 if isinstance(node.op,ast.USub) else 1)*visit(node.operand)
        if isinstance(node,ast.BinOp):
            a,b=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Add):return a+b
            if isinstance(node.op,ast.Sub):return a-b
            if isinstance(node.op,ast.Mult):return a*b
            if isinstance(node.op,ast.Div):return a/b
            if isinstance(node.op,ast.Pow) and abs(b)<=20:return a**b
        raise ValueError('Unsupported expression.')
    result=visit(tree)
    if not math.isfinite(result) or result<=0:raise ValueError('Parameter must be positive.')
    return result

def parse_page(text,material,x=None):
    """Extract supported numeric/formula rows, excluding DOS/heavy-hole substitution."""
    parser=_Tables();parser.feed(text)
    result={}
    for cells in parser.rows:
        label=re.sub(r'\s+',' ',cells[0]).strip().lower()
        value=re.sub(r'\s+','',cells[1]).replace('\xa0','')
        key=None
        if label.startswith('dielectric constant') and 'high' not in label:key='relative_permittivity'
        elif label.startswith('intrinsic carrier concentration'):key='intrinsic_cm3'
        elif label.startswith('mobility electrons'):key='mobility_e_cm2_Vs'
        elif label.startswith('mobility holes'):key='mobility_h_cm2_Vs'
        elif label.startswith('effective electron mass') and material=='GaAs':key='mass_e_m0'
        elif label.startswith('effective electron mass') and material=='AlGaAs' and x is not None and x<.45:key='mass_e_m0'
        elif label.startswith('conductivity effective mass') and material=='AlGaAs' and x is not None and x>.45:key='mass_e_m0'
        elif label.startswith('effective hole masses'):
            key='light_hole_mass_m0' if 'lp' in label else 'heavy_hole_mass_m0'
        if not key:continue
        # Stop before units or a composition-domain annotation; arbitrary HTML
        # and unknown text cannot become executable Python.
        value=value.lstrip('≤<≈~=')
        expr=re.match(r'[0-9.x+*/^()·×−-]+',value)
        if not expr:continue
        expression=expr.group(0).rstrip('(')
        # AlGaAs intrinsic values are a multi-composition table, not one scalar.
        if material=='AlGaAs' and key=='intrinsic_cm3':continue
        try:result[key]=_number(expression,x)
        except (ValueError,SyntaxError,ZeroDivisionError,OverflowError):continue
    return result

def _bundled(material,x):
    values={};sources={};notes=['Ioffe bulk parameters at 300 K; mobility entries are weak-doping/basic bounds, not a doping-dependent fit. Review these starting values for the actual sample.']
    def put(key,value,page):values[key]=value;sources[key]=BASE+material+'/'+page
    if material=='Si':
        put('relative_permittivity',11.7,'basic.html');put('intrinsic_cm3',1e10,'bandstr.html')
        put('mobility_e_cm2_Vs',1400.,'electric.html');put('mobility_h_cm2_Vs',450.,'electric.html')
        # Explicitly retain the paper conductivity masses, not Ioffe DOS masses.
        for key,value in [('mass_e_m0',.26),('mass_h_m0',.39)]:
            values[key]=value;sources[key]='https://doi.org/10.1109/JQE.1987.1073206'
        notes+=['Si mobilities are Ioffe upper bounds (≤1400 and ≤450 cm²/V·s).','Si conductivity masses .26/.39 come from Soref–Bennett p.127, not from relabeling Ioffe heavy-hole or DOS masses.']
    elif material=='GaAs':
        put('relative_permittivity',12.9,'basic.html');put('intrinsic_cm3',2.1e6,'bandstr.html')
        put('mass_e_m0',.063,'basic.html')
        put('heavy_hole_mass_m0',.51,'basic.html');put('light_hole_mass_m0',.082,'basic.html')
        put('mobility_e_cm2_Vs',8500.,'electric.html');put('mobility_h_cm2_Vs',400.,'electric.html')
        notes+=['GaAs mobilities are basic-table upper bounds (≤8500 and ≤400 cm²/V·s), not measured sample values.','Ioffe GaAs electron mass .063 differs from the slide .067. Ioffe heavy/light hole masses are .51/.082; neither is silently used as the conductivity mass. Enter a suitable hole conductivity mass.']
    else:
        put('relative_permittivity',12.90-2.84*x,'basic.html')
        put('heavy_hole_mass_m0',.51+.25*x,'basic.html');put('light_hole_mass_m0',.082+.068*x,'basic.html')
        if x<.45:put('mass_e_m0',.063+.083*x,'basic.html')
        elif x>.45:put('mass_e_m0',.26,'basic.html')
        if 0<x<.45:put('mobility_e_cm2_Vs',8000-22000*x+10000*x*x,'ebasic.html')
        elif .45<x<1:put('mobility_e_cm2_Vs',-255+1160*x-720*x*x,'ebasic.html')
        put('mobility_h_cm2_Vs',370-970*x+740*x*x,'ebasic.html')
        table={.1:2.1e5,.3:2.1e3,.5:2.5e2,.8:4.3e1}
        exact=next((v for k,v in table.items() if abs(k-x)<1e-10),None)
        if exact is not None:put('intrinsic_cm3',exact,'bandstr.html')
        notes+=['AlGaAs values evaluated at Al mole fraction x='+format(x,'.6g')+'.','Electron mass uses the Γ band expression below x=.45 and conductivity mass .26 above .45; the DOS mass .85−.14x is not substituted. Crossover x=.45 requires user input.','Hole conductivity mass is not supplied as a scalar by these tables. Heavy/light hole masses are shown for reference; provide a conductivity mass appropriate to band populations.','AlGaAs intrinsic density is auto-filled only at tabulated x=.1,.3,.5,.8. No unverified interpolation is used.','AlGaAs mobilities use the positive-sign formulas on ebasic.html; the separate Hall page has inconsistent printed signs. They remain approximate basic/low-doping values.']
    return dict(material=material,alloy_x=x,values=values,field_sources=sources,sources=sorted(set(sources.values())),notes=notes,
                temperature_k=300.,status='bundled-cache',reviewed_date=REVIEWED,fetched_at=None,
                missing=[k for k in FIELDS if k not in values])

def _fetch(url):
    # No disabled TLS verification and no caller-controlled destination.
    request=urllib.request.Request(url,headers={'User-Agent':'OpticalDesignStudio/1.2 material-parameter lookup'})
    with urllib.request.urlopen(request,timeout=4) as response:
        if not response.url.startswith(BASE):raise ValueError('Unexpected source redirect.')
        data=response.read(1_000_001)
        if len(data)>1_000_000:raise ValueError('Parameter page is too large.')
        return data.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')

def material_parameters(material,x=None,refresh=False):
    """Return values/sources/notes/status. Safe to call from a UI worker.

    With refresh=False the reviewed local dataset (or session cache) is immediate.
    refresh=True tries three official HTTPS pages concurrently, with 4 s timeouts.
    """
    if material not in ('Si','GaAs','AlGaAs'):raise ValueError('Ioffe presets support Si, GaAs and AlGaAs.')
    if material=='AlGaAs':
        if isinstance(x,bool):raise ValueError('Al mole fraction must be a number from 0 to 1.')
        try:x=float(x)
        except (ValueError,TypeError):raise ValueError('Specify Al mole fraction x.') from None
        if not math.isfinite(x) or not 0<=x<=1:raise ValueError('Al mole fraction must be from 0 to 1.')
    else:x=None
    key=(material,x)
    if not refresh and key in _CACHE:return copy.deepcopy(_CACHE[key])
    record=copy.deepcopy(_CACHE.get(key,_bundled(material,x)))
    if not refresh:return record
    pages=['basic.html','bandstr.html','ebasic.html' if material=='AlGaAs' else 'electric.html']
    urls=[BASE+material+'/'+p for p in pages]
    live_fields=set();errors=[]
    def request(url):
        try:return url,parse_page(_fetch(url),material,x),None
        except Exception as exc:return url,{},type(exc).__name__
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(request,urls))
    for url,values,error in results:
        if error:errors.append(error);continue
        for field,value in values.items():
            # Never turn an ambiguous live table into a conductivity hole mass.
            if field=='mass_h_m0':continue
            record['values'][field]=value;record['field_sources'][field]=url;live_fields.add(field)
    if live_fields:
        record['status']='mixed'
        record['fetched_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        record['notes'].append('Live HTTPS refresh parsed: '+', '.join(sorted(live_fields))+'. Other values retain their stated cached/source provenance.')
    else:
        record['notes'].append('Live refresh unavailable or source tables unrecognized; retained reviewed cached data. '+', '.join(sorted(set(errors))))
    record['sources']=sorted(set(record['field_sources'].values()))
    record['missing']=[k for k in FIELDS if k not in record['values']]
    _CACHE[key]=copy.deepcopy(record)
    return record
