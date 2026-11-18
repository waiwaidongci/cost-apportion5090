import {heading} from '../components/common/header.js';import {table} from '../components/common/table.js';import {status} from '../components/common/status.js';import {esc} from '../utils/format.js';import {reciprocalReport} from '../components/reciprocal_report.js';import {ratiosSumToOne} from '../utils/reciprocal.js';

const blankRule={
  version:'互供关系-新版本',
  services:['后勤','车队'],
  beneficiaries:['生产一厂','生产二厂'],
  rows:[
    {source:'后勤',allocations:[{target:'车队',ratio:'1/2'},{target:'生产一厂',ratio:'1/4'},{target:'生产二厂',ratio:'1/4'}]},
    {source:'车队',allocations:[{target:'生产一厂',ratio:'1/2'},{target:'生产二厂',ratio:'1/2'}]},
  ],
};

export function reciprocal(c,d){
 const role=d?.session?.role||'';
 const runs=d.runs_reciprocal||[];
 const selected=runs.find(r=>r.id===d.reciprocalSelected)||runs[0];
 const rule=blankRule;
 const deptOptions=[...rule.services,...rule.beneficiaries];
 return heading('RECIPROCAL ALLOCATION / 04','服务部门互供核算（代数分配法）','登记服务部门→服务/受益部门的有理数比例，每行合计为一；按自身费用＋转入费用求精确解，仅受益部门取整、余分按部门名稳定分配且守恒。封闭循环即使零费用也拒绝。保留原工时权重分摊方式，互不影响。')
 + `<section class="rec-config">
  <h2>一、登记互供关系版本</h2>
  <p class="muted">比例接受分数（如 1/3）或有限小数（如 0.25、0.000001）。提交前自动校验每个服务部门行合计是否恰为 1。</p>
  <form id="reciprocal-rule-form">
   <div class="form-grid">
    <label>关系版本名<input name="version" value="${esc(rule.version)}" required></label>
    <label>服务部门（逗号分隔）<input id="rec-services" value="${esc(rule.services.join('，'))}" required></label>
    <label>受益部门（逗号分隔）<input id="rec-beneficiaries" value="${esc(rule.beneficiaries.join('，'))}" required></label>
   </div>
   <datalist id="rec-dept-list">${deptOptions.map(x=>`<option value="${esc(x)}">`).join('')}</datalist>
   <div id="rec-rows">
     ${rule.rows.map(r=>`
     <div class="rec-row" data-source="${esc(r.source)}">
       <h4>服务部门 <input class="rec-source" value="${esc(r.source)}" style="width:auto;display:inline-block;min-width:120px"> 的转出比例
         <button type="button" class="rec-row-remove">删除该行</button></h4>
       <div class="rec-alloc-list">
         ${r.allocations.map(a=>`
         <div class="rec-alloc">
           <label>目标部门<input class="rec-target" value="${esc(a.target)}" list="rec-dept-list"></label>
           <label>比例（分数/小数）<input class="rec-ratio" value="${esc(a.ratio)}" placeholder="如 1/3 或 0.25"></label>
           <button type="button" class="rec-alloc-remove">删除</button>
         </div>`).join('')}
       </div>
       <button type="button" class="rec-alloc-add">增加转出目标</button>
       <p class="rec-sum"></p>
     </div>`).join('')}
   </div>
   <div class="rec-form-actions">
     <button type="button" id="rec-row-add">增加服务部门行</button>
     <button type="button" id="rec-precheck">预检封闭环与行合计</button>
     <button type="submit" ${role==='admin'?'':'disabled title="仅负责人可登记互供关系"'}>登记新版本（仅负责人）</button>
   </div>
   <pre id="rec-precheck-out" class="rec-precheck" role="status"></pre>
  </form>
  <h2>已登记互供关系</h2>
  ${table((d.rules_reciprocal||[]).map(r=>({编号:r.id,版本:r.version,服务部门:(r.data.services||[]).join('、'),受益部门:(r.data.beneficiaries||[]).join('、'),登记时间:new Date(r.created*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})})))}
 </section>
 <section class="rec-runs">
  <h2>二、排队互供核算（冻结同一时点底稿与关系）</h2>
  <form id="reciprocal-run-form" class="inline-form">
   <label>任务名称<input name="name" value="互供十一月核算" required></label>
   <label>互供关系版本<select name="rule_id">${(d.rules_reciprocal||[]).map(r=>`<option value="${r.id}">${esc(r.version)}</option>`).join('')}</select></label>
   <label>期间<select name="period"><option>全部</option>${(d.periods||[]).map(p=>`<option>${esc(p.name)}</option>`).join('')}</select></label>
   <button ${role==='admin'||role==='analyst'?'':'disabled title="仅负责人或分析师可排队核算"'}>排队互供核算</button>
  </form>
  <div class="run-layout">
   <aside class="run-list">${(runs.length?runs:[]).map(r=>`<button class="rec-select-run" data-id="${r.id}">${esc(r.name)} ${status(r.status)}</button>`).join('')||'<p class="empty">暂无互供核算任务。</p>'}</aside>
   <div id="reciprocal-result">${reciprocalReport(selected,role)}</div>
  </div>
 </section>`;
}

// 从编辑器收集规则对象，同时做行合计校验；返回 {data, errors}
export function collectRule(form){
 const split=v=>v.split(/[，,、]/).map(s=>s.trim()).filter(Boolean);
 const services=split(form.querySelector('#rec-services').value);
 const beneficiaries=split(form.querySelector('#rec-beneficiaries').value);
 const version=form.querySelector('[name=version]').value.trim();
 const rows=[];const errors=[];
 form.querySelectorAll('#rec-rows .rec-row').forEach(card=>{
  const source=card.querySelector('.rec-source').value.trim();
  const allocations=[];const ratioTexts=[];
  card.querySelectorAll('.rec-alloc').forEach(al=>{
   const target=al.querySelector('.rec-target').value.trim();
   const ratio=al.querySelector('.rec-ratio').value.trim();
   if(target&&ratio){allocations.push({target,ratio});ratioTexts.push(ratio);}
  });
  let sumOk=false;
  try{sumOk=ratioTexts.length&&ratiosSumToOne(ratioTexts);}catch(e){errors.push(`${source}：${e.message}`);}
  card.querySelector('.rec-sum').textContent=ratioTexts.length?(sumOk?'✓ 本行合计 = 1':'✗ 本行合计 ≠ 1，请修正后再提交'):'';
  card.querySelector('.rec-sum').className='rec-sum '+(sumOk?'ok':'bad');
  if(!sumOk&&ratioTexts.length)errors.push(`服务部门 ${source} 的转出比例合计必须恰好为 1`);
  rows.push({source,allocations});
 });
 const data={version,services,beneficiaries,rows};
 return {data,errors};
}
