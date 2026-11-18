import {esc} from './format.js';

// 把页面输入的有理数精确解析为 BigInt 分子/分母；接受 1/3、0.25、0.000001、1e-6
export function parseRatio(text){
  const t=String(text).trim();
  if(!t) throw new Error('比例不能为空');
  if(t.includes('/')){
    const [a,b]=t.split('/');
    if(!/^[+-]?\d+$/.test(a.trim())||!/^[+-]?\d+$/.test(b.trim())) throw new Error('分数须为 分子/分母（整数）');
    const n=BigInt(a.trim()), d=BigInt(b.trim());
    if(d<=0n) throw new Error('分数分母必须为正整数');
    if(n<0n) throw new Error('比例不能为负');
    return {n,d};
  }
  if(!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(t)) throw new Error('比例数值不合法');
  // 展开科学计数法为普通十进制字符串，避免浮点
  let plain=t;
  if(/[eE]/.test(t)){
    const [mantissa,expPart]=t.split(/[eE]/);
    const exp=Number(expPart);
    const sign=mantissa.startsWith('-')?'-':'';
    const [intPart='',fracPart='']=mantissa.replace(/^[+-]/,'').split('.');
    const digits=(intPart+fracPart);
    const point=intPart.length+exp;
    if(point<=0) plain=sign+'0.'+'0'.repeat(-point)+digits.replace(/^0+/,'');
    else if(point>=digits.length) plain=sign+digits+'0'.repeat(point-digits.length);
    else plain=sign+digits.slice(0,point)+'.'+digits.slice(point);
  }
  const negative=plain.startsWith('-');
  if(negative) throw new Error('比例不能为负');
  const [whole='',frac='']=plain.replace(/^[+-]/,'').split('.');
  const numerator=BigInt((whole+frac).replace(/^0+(?=\d)/,'')||'0');
  const denominator=10n**BigInt(frac.length);
  return {n:numerator,d:denominator};
}

// 用 BigInt 精确校验一组比例合计是否恰为 1
export function ratiosSumToOne(texts){
  let num=0n, den=1n;
  for(const t of texts){
    const {n,d}=parseRatio(t);
    num=num*d+n*den; den=den*d;
  }
  return num===den;
}

export const rowCard=(source,targets,key)=>`
<div class="rec-row" data-source="${esc(source)}">
  <h4>服务部门 ${esc(source)} 的转出比例
    <button type="button" class="rec-row-remove" data-source="${esc(source)}">删除该行</button>
  </h4>
  <div class="rec-alloc-list">
    ${targets.map(([target,ratio])=>`
    <div class="rec-alloc">
      <label>目标部门<input class="rec-target" value="${esc(target)}" list="rec-dept-list"></label>
      <label>比例（分数/小数）<input class="rec-ratio" value="${esc(ratio)}" placeholder="如 1/3 或 0.25"></label>
      <button type="button" class="rec-alloc-remove">删除</button>
    </div>`).join('')}
  </div>
  <button type="button" class="rec-alloc-add">增加转出目标</button>
  <p class="rec-sum"></p>
</div>`;
