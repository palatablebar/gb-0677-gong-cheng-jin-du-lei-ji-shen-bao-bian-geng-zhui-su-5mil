from app.values import number
from app.reasons import reject
from app.errors import DomainError
def evaluate(rows,context):
    good=[];bad=[];overrides=context.get("parameters",{}).get("previous_revisions",{});seen=set();consumed=set()
    for row in sorted(rows,key=lambda x:(x["item"],x["period"],x["claim_id"])):
        key=(row["item"],row["period"])
        if key in seen:bad.append(reject(row,"DUPLICATE_PERIOD","同清单同周期重复申报"));continue
        seen.add(key)
        base=row.get("split_base")
        if row["claim_id"] in overrides:prev=number(overrides[row["claim_id"]])
        elif base is not None and row["item"] not in consumed:
            consumed.add(row["item"]);prev=number(base);row={**row,"previous_source":"split_mapping"}
        else:prev=number(row["previous_qty"])
        if prev<0:raise DomainError("BAD_PREVIOUS","前审累计量不能为负")
        incremental=number(row["cumulative_qty"])-prev
        if incremental<0 and row.get("reversal")!="approved":bad.append(reject(row,"REVERSAL_REQUIRED","负进度缺少已批冲回凭证"));continue
        good.append({**row,"approved_previous":str(prev),"increment_qty":str(incremental),"gross_amount":str(incremental*number(row["unit_price"]))})
    return {"rows":good,"quarantine":bad,"metrics":{"accepted":len(good),"negative_claims":sum(number(r["increment_qty"])<0 for r in good),"split_based":sum(r.get("previous_source")=="split_mapping" for r in good)}}
