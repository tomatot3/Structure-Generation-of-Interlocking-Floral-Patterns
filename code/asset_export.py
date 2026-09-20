"""Export semantic geometry and an unlabelled appearance-conditioning image."""
import json,os,shutil,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
from export_batch_svgs import render_case_svg

NS='{http://www.w3.org/2000/svg}'
ET.register_namespace('',NS[1:-1])

def export_asset(folder,analysis,mounts,selection,provenance,inkscape=None):
    folder=Path(folder)
    structure={'schema':'papera-structural-asset-v1','case_id':provenance['source_case'],
        'coordinate_note':'Coordinates normalized by repeat width W; central repeat shift is zero.',
        'analysis':{k:analysis[k] for k in ['coordinate_system','backbone','flowers']},
        'flower_mount_plan':{'mounts':mounts['mounts']},
        'selection':{'feasible':selection['feasible'],'selected_candidates':[
            {k:u[k] for k in ['candidate_id','branch_unit_id','source_lane_id','curves','parent_graph'] if k in u}
            for u in selection['selected_candidates']]}}
    (folder/'structure.json').write_text(json.dumps(structure,ensure_ascii=False,indent=2),'utf-8')
    svg=render_case_svg(analysis,mounts,selection,provenance,repeat='triple',palette='role')
    (folder/'structure.svg').write_text(svg,'utf-8')
    root=ET.fromstring(svg)
    for child in list(root):
        if child.get('data-role')=='unit_boundary':root.remove(child)
    for element in root.iter():
        if element.tag in {NS+'rect',NS+'ellipse'}:element.set('fill','#ffffff')
    ys=[q[1] for u in selection['selected_candidates'] for c in u['curves']
        for seg in c['cubic_segments'] for q in [seg['p0'],seg['p1'],seg['p2'],seg['p3']]]
    ys += [r['point'][1] for r in analysis['backbone']['samples']]
    ys += [q[1] for m in mounts['mounts'] for q in m['centerline']]
    ys += [f['center'][1]+sign*f['ry'] for f in analysis['flowers'] for sign in [-1,1]]
    vb=list(map(float,root.get('viewBox').split()))
    ymin=min(vb[1],min(ys)-.035);ymax=max(vb[1]+vb[3],max(ys)+.035)
    root.set('viewBox',f'{vb[0]} {ymin} {vb[2]} {ymax-ymin}')
    root.set('width','2048');root.set('height',str(round(2048*(ymax-ymin)/vb[2])))
    bg=root.find(NS+'rect');bg.set('y',str(ymin));bg.set('height',str(ymax-ymin))
    ET.ElementTree(root).write(folder/'render_input.svg',encoding='utf-8',xml_declaration=True)
    if inkscape:
        executable=shutil.which(str(inkscape)) or str(Path(inkscape).resolve())
        subprocess.run([executable,str((folder/'render_input.svg').resolve()),'--export-type=png',
            '--export-width=2048',f'--export-filename={(folder/"render_input.png").resolve()}'],
            check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
