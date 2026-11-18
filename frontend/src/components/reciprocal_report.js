import {esc,fmt,time} from '../utils/format.js';import {table} from './common/table.js';import {status} from './common/status.js';

const metrics=result=>`<div class="metrics">${Object.entries(result.summary).map(([k,v])=>`<div><small>${esc(k)}</small><strong>${fmt(v)}</strong></div>`).join('')}</div>`;

export function reciprocalReport(run,role){
 if(!run)return '<p class="empty">选择一个互供核算任务查看精确份额与复核状态。</p>';
 return `<section class="report">
  <div class="report-top"><h2>${esc(run.name)}</h2>${status(run.status)}</div>
  <p>互供关系：${esc(run.rule_version)} · 期间 ${esc(run.period)} · 冻结来源 ${run.snapshot.sources.length} 行 · ${run.approved?'负责人已复核':'待复核'}</p>
  <p class="checksum">SHA256 ${esc(run.checksum)}</p>
  <p>排队时间 ${time(run.created)}${run.finished?' · 完成时间 '+time(run.finished):''}</p>
  ${run.error?'<p class="error">'+esc(run.error)+'</p>':''}
  ${run.result?`
   <p class="method">${esc(run.result.method)}</p>
   ${run.result.warnings?.length?'<p class="warning">'+run.result.warnings.map(esc).join('；')+'</p>':''}
   ${metrics(run.result)}
   <h3>封闭环诊断</h3>
   <p>无外流部门：${run.result.diagnosis.trapped.length?esc(run.result.diagnosis.trapped.join('、')):'无'}；
   封闭环分组：${run.result.diagnosis.closed_groups.length?esc(run.result.diagnosis.closed_groups.map(g=>'('+g.join('、')+')').join('；')):'无'}</p>
   <p>独立精确解交叉校验：${run.result.cross_check.performed?(run.result.cross_check.matched?'通过（'+esc(run.result.cross_check.solver)+'）':'不一致，已拒绝'):'未触发'}</p>
   <h3>受益部门取整分摊（整数分 · 守恒）</h3>
   ${table(run.result.rows)}
   <details><summary>受益部门精确分数份额（不取整）</summary>${table(run.result.share_rows)}</details>
   <details><summary>服务部门总成本精确解（自身费用＋转入费用）</summary>${table(run.result.service_rows)}</details>
   <details><summary>冻结底稿与互供关系快照</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px">${esc(JSON.stringify(run.snapshot,null,2))}</pre></details>
   <div class="report-actions">
     <button id="reciprocal-export" data-id="${run.id}">下载互供 CSV</button>
     ${run.status==='completed'?`<form id="reciprocal-approve" data-id="${run.id}">
       <label>负责人复核说明（至少4字）<input name="note" minlength="4" placeholder="核对互供口径、固定点与守恒结论" required></label>
       <button ${run.approved||role!=='admin'?'disabled':''}>${run.approved?'已复核':(role==='admin'?'复核互供核算':'仅负责人可复核')}</button>
     </form>`:''}
   </div>`:''}
  <p>${esc(run.review||'尚未填写复核说明')}</p>
 </section>`;
}
