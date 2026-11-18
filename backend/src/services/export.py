import csv,io,json
from fastapi import HTTPException
def csv_text(result):
 rows=result.get('rows',[])
 if not rows: raise HTTPException(409,'尚无结果')
 stream=io.StringIO();keys=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(stream,fieldnames=keys);w.writeheader()
 for row in rows: w.writerow({k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in row.items()})
 return '\ufeff'+stream.getvalue()
def _section(stream,title,rows):
 if not rows: return
 stream.write(('# ' if stream.tell()==0 else '\n# ')+title+'\n')
 writer=csv.DictWriter(stream,fieldnames=list(rows[0].keys()))
 writer.writeheader()
 for item in rows:
  writer.writerow({k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in item.items()})
def reciprocal_csv_text(result):
 if not result or not result.get('rows'):
  raise HTTPException(409,'尚无互供核算结果')
 stream=io.StringIO()
 _section(stream,'受益部门取整分摊（整数分，守恒）',result['rows'])
 _section(stream,'受益部门精确分数份额',result.get('share_rows',[]))
 _section(stream,'服务部门总成本精确解（自身费用+转入费用）',result.get('service_rows',[]))
 return '\ufeff'+stream.getvalue()
