// failure map page; data comes from the two json script tags rendered by map_render.py
const SNAP=JSON.parse(document.getElementById('map-data').textContent);
const COL=JSON.parse(document.getElementById('map-colours').textContent);
const PNG=new URLSearchParams(location.search).has('png');
if(PNG)document.body.classList.add('png');
const svg=d3.select('#graph'),root=svg.append('g');
svg.call(d3.zoom().scaleExtent([.2,6]).on('zoom',e=>root.attr('transform',e.transform)));
const $=id=>document.getElementById(id);
function radius(n){return n.type==='repo'?14:n.type==='module'?9:n.type==='task'?4:4+2.2*Math.sqrt(n.blast_radius||0)}
function fill(n){if(n.type==='repo')return 'var(--accent)';if(n.type==='module')return 'var(--muted)';
if(n.type==='task')return COL[n.family]||'#999';return n.families.length?(COL[n.families[0]]||'#999'):'#b5b5ba'}
function build(m){
const nodes=[{id:'repo:'+m.target,type:'repo',name:m.target}],links=[];
const mods=[...new Set(m.nodes.map(n=>n.module))].sort();
for(const md of mods){nodes.push({id:'mod:'+md,type:'module',name:md});links.push({source:'repo:'+m.target,target:'mod:'+md,kind:'contains'})}
const byId={};for(const n of m.nodes){const x=Object.assign({type:'fn',tasks:[]},n);byId[n.id]=x;nodes.push(x);
links.push({source:'mod:'+n.module,target:n.id,kind:'contains'})}
for(const e of m.edges)links.push({source:e.source,target:e.target,kind:e.kind});
for(const t of m.tasks){const host=byId[t.node_id];if(!host)continue;host.tasks.push(t);
const x=Object.assign({id:'task:'+t.task_id,type:'task',name:t.task_id,host:host.id},t);nodes.push(x);
links.push({source:x.id,target:host.id,kind:'task'})}
return {nodes,links,byId,m};
}
let G=null,sel=null;
function layout(g){
// fixed tick count instead of an animated run, so the png snapshot sees the final layout
const sim=d3.forceSimulation(g.nodes)
.force('link',d3.forceLink(g.links).id(d=>d.id).distance(l=>l.kind==='task'?12:l.kind==='contains'?40:60).strength(l=>l.kind==='task'?1:.4))
.force('charge',d3.forceManyBody().strength(d=>d.type==='task'?-8:-70))
.force('collide',d3.forceCollide(d=>radius(d)+2)).force('center',d3.forceCenter(0,0)).stop();
for(let i=0;i<300;i++)sim.tick();
}
function draw(){
root.selectAll('*').remove();
// fit the finished layout instead of centring on the window, so small maps fill the png
const xs=G.nodes.map(d=>d.x),ys=G.nodes.map(d=>d.y),pad=60;
const x0=Math.min(...xs)-pad,y0=Math.min(...ys)-pad;
svg.attr('viewBox',[x0,y0,Math.max(...xs)+pad*2-x0,Math.max(...ys)+pad-y0].join(' '));
G.linkSel=root.append('g').selectAll('line').data(G.links).join('line').attr('class',l=>'link '+(l.kind==='contains'||l.kind==='task'?l.kind:'dep'))
.attr('x1',l=>l.source.x).attr('y1',l=>l.source.y).attr('x2',l=>l.target.x).attr('y2',l=>l.target.y);
G.nodeSel=root.append('g').selectAll('path').data(G.nodes).join('path')
.attr('d',d=>d.type==='task'?d3.symbol(d3.symbolSquare,60)():d3.symbol(d3.symbolCircle,Math.PI*radius(d)**2)())
.attr('transform',d=>`translate(${d.x},${d.y})`).attr('fill',fill)
.attr('class',d=>'n'+(d.type==='fn'&&d.covered===false?' uncovered':d.type==='fn'&&d.covered===true?' covered':''))
.on('click',(e,d)=>show(d));
G.nodeSel.append('title').text(d=>d.name);
G.labelSel=root.append('g').selectAll('text').data(G.nodes.filter(d=>d.type!=='task')).join('text')
.attr('x',d=>d.x+radius(d)+2).attr('y',d=>d.y+3).text(d=>d.type==='fn'?d.name:d.name.split('.').pop());
apply();
}
function visible(d){
const fam=$('fam').value,kind=$('kind').value,unc=$('unc').checked,all=$('all').checked;
if(d.type==='repo'||d.type==='module')return true;
if(d.type==='task')return visible(G.byId[d.host])&&(!fam||d.family===fam);
if(!all&&!d.families.length&&!d.tasks.length)return false;
if(fam&&!d.families.includes(fam)&&!d.tasks.some(t=>t.family===fam))return false;
if(kind&&d.kind!==kind)return false;
if(unc&&d.covered!==false)return false;
return true;
}
function apply(){
const q=$('q').value.trim().toLowerCase();const vis=new Set(G.nodes.filter(visible).map(d=>d.id));
const hit=d=>q&&(d.name.toLowerCase().includes(q)||(d.file||'').toLowerCase().includes(q));
G.nodeSel.attr('display',d=>vis.has(d.id)?null:'none').classed('dim',d=>!!q&&!hit(d)).classed('hit',d=>!!q&&hit(d));
G.labelSel.attr('display',d=>vis.has(d.id)&&(d.type!=='fn'||!q||hit(d)||G.nodes.length<120)?null:'none');
G.linkSel.attr('display',l=>vis.has(l.source.id)&&vis.has(l.target.id)?null:'none');
$('count').textContent=`${[...vis].filter(i=>!i.startsWith('repo:')&&!i.startsWith('mod:')&&!i.startsWith('task:')).length} functions shown`;
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function show(d){
const p=$('detail');
if(d.type==='task'){p.innerHTML=`<h3>${esc(d.task_id)}</h3><p>task · ${esc(d.family)} · ${esc(d.difficulty)}</p><p>on <a href="#" data-id="${esc(d.host)}">${esc(G.byId[d.host].name)}</a></p>`}
else if(d.type!=='fn'){const kids=G.m.nodes.filter(n=>d.type==='repo'||n.module===d.name);
p.innerHTML=`<h3>${esc(d.name)}</h3><p>${d.type} · ${kids.length} functions, ${kids.filter(n=>n.families.length).length} tagged</p>`}
else{const calls=G.m.edges.filter(e=>e.source===d.id),by=G.m.edges.filter(e=>e.target===d.id);
const li=(es,k)=>es.map(e=>`<li><a href="#" data-id="${esc(e[k])}">${esc(G.byId[e[k]].name)}</a> <span class="muted">${esc(e.kind)}</span></li>`).join('')||'<li class="muted">none</li>';
p.innerHTML=`<h3>${esc(d.name)}</h3><p class="muted">${esc(d.file)}<br>${esc(d.module)} · ${esc(d.kind)}</p>
<p>families: ${d.families.map(f=>`<span style="color:${COL[f]||'inherit'}">${esc(f)}</span>`).join(', ')||'<span class="muted">none</span>'}<br>
blast radius ${d.blast_radius} · ${esc(d.difficulty||'-')} · ${d.covered===true?'test-covered':d.covered===false?'<b>not covered by repo tests</b>':'coverage unknown'}</p>
<p>tasks:</p><ul>${d.tasks.map(t=>`<li>${esc(t.task_id)} <span class="muted">${esc(t.family)}</span></li>`).join('')||'<li class="muted">none yet</li>'}</ul>
<p>calls / uses:</p><ul>${li(calls,'target')}</ul><p>used by:</p><ul>${li(by,'source')}</ul>`}
p.querySelectorAll('a[data-id]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();show(G.byId[a.dataset.id])}));
}
function pick(i){
const m=SNAP[i];G=build(m);layout(G);
const kinds=[...new Set(m.nodes.map(n=>n.kind))].sort(),fams=Object.keys(COL).filter(f=>m.nodes.some(n=>n.families.includes(f)));
$('kind').innerHTML='<option value="">all kinds</option>'+kinds.map(k=>`<option>${esc(k)}</option>`).join('');
$('fam').innerHTML='<option value="">all families</option>'+fams.map(f=>`<option>${esc(f)}</option>`).join('');
$('legend').innerHTML=fams.map(f=>`<span><i style="background:${COL[f]}"></i>${esc(f)}</span>`).join('')+
'<span><i style="background:#b5b5ba"></i>untagged</span><span class="muted">dashed red ring = not covered by repo tests · square = task · size = blast radius</span>';
$('all').checked=m.nodes.length<=400;
document.querySelectorAll('.cov').forEach((c,j)=>c.hidden=j!==i);
draw();
}
const tsel=$('target');tsel.innerHTML=SNAP.map((m,i)=>`<option value="${i}">${esc(m.target)}</option>`).join('');
tsel.addEventListener('change',()=>pick(+tsel.value));
for(const id of ['q','fam','kind','unc','all'])$(id).addEventListener('input',apply);
if(SNAP.length)pick(0);
