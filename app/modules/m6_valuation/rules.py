from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError
def split_reconcile(output,context):
    "拆分批次本期对账：按新码汇总承接量、本期增量与净额，并回指旧码已审累计。"
    rows=[row for row in output if row.get("split_id")]
    if not rows: return None
    targets={}
    for row in rows:
        slot=targets.setdefault(row["item"],{"item":row["item"],"source_item":row.get("source_item",""),"split_id":row.get("split_id",""),"carryover":str(row.get("split_base","0")),"increment_total":Decimal(0),"expected_total":Decimal(0)})
        slot["increment_total"]+=Decimal(str(row.get("increment_qty","0")))
        slot["expected_total"]+=Decimal(str(row.get("expected","0")))
    carryover=sum((Decimal(slot["carryover"]) for slot in targets.values()),Decimal(0))
    block={"split_id":rows[0].get("split_id",""),"source_item":rows[0].get("source_item",""),"carryover_total":str(carryover),"increment_total":str(sum((slot["increment_total"] for slot in targets.values()),Decimal(0))),"expected_total":str(sum((slot["expected_total"] for slot in targets.values()),Decimal(0))),"targets":[{**slot,"increment_total":str(slot["increment_total"]),"expected_total":str(slot["expected_total"])} for slot in targets.values()]}
    bill=(context.get("billitems") or {}).get("metrics",{}).get("split") if isinstance(context,dict) else None
    if bill:
        block["effective"]=bill.get("effective")
        block["source_cumulative"]=bill.get("baseline")
        if bill.get("baseline") is not None: block["carryover_balanced"]=carryover==Decimal(str(bill["baseline"]))
    return block
def evaluate(rows,context):
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows)}
    if intake:
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+excluded)
    else:m.update(input=len(accepted)+len(rejected),excluded=0,balanced=True)
    output=[]
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        output.append({**row,"difference":str(expected-reported),"status":"通过" if expected==reported else "差异"})
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),differences=sum(r["status"]=="差异" for r in output))
    split=split_reconcile(output,context)
    if split: m["split"]=split
    return {"rows":output,"quarantine":[],"metrics":m}
