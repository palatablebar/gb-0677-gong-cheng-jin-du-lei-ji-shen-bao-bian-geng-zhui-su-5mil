from datetime import datetime
from decimal import Decimal
from app.values import number
from app.reasons import reject
from app.errors import DomainError
ITEMS={"钢筋":"001","001":"001","混凝土":"002","002":"002"}
def valid_period(value):
    if not isinstance(value,str) or len(value)!=7: return False
    try: datetime.strptime(value,"%Y-%m"); return True
    except ValueError: return False
def split_amount(value,field):
    try: return number(value)
    except DomainError as e: raise DomainError("SPLIT_INVALID",f"{field}无效:{e.message}") from e
def prepare_split(mapping):
    "校验拆分映射结构；任何非法都拒绝整批切换，不产生半切换状态。"
    if not isinstance(mapping,dict): raise DomainError("SPLIT_INVALID","拆分映射需要对象")
    split_id=mapping.get("split_id")
    if not isinstance(split_id,str) or not split_id.strip(): raise DomainError("SPLIT_INVALID","拆分批次号缺失")
    key=mapping.get("source_item")
    source=ITEMS.get(key) if isinstance(key,str) else None
    if source is None: raise DomainError("SPLIT_INVALID","旧清单编码未登记")
    effective=mapping.get("effective")
    if not valid_period(effective): raise DomainError("SPLIT_INVALID","拆分生效周期需要YYYY-MM")
    targets=mapping.get("targets")
    if not isinstance(targets,list) or not targets: raise DomainError("SPLIT_INVALID","拆分去向需要非空列表")
    registry={};carryover={};entries=[]
    for target in targets:
        if not isinstance(target,dict): raise DomainError("SPLIT_INVALID","拆分去向需要对象")
        item=target.get("item")
        if not isinstance(item,str) or not item.strip(): raise DomainError("SPLIT_INVALID","新清单编码缺失")
        item=item.strip()
        if item==source or ITEMS.get(item,item) in ITEMS.values() or item in registry:
            raise DomainError("SPLIT_INVALID",f"新清单编码{item}与既有编码冲突")
        label=target.get("label")
        if label is not None:
            if not isinstance(label,str) or not label.strip(): raise DomainError("SPLIT_INVALID","新清单别名需要文本")
            label=label.strip()
            if ITEMS.get(label,label) in ITEMS.values() or label in registry:
                raise DomainError("SPLIT_INVALID",f"新清单别名{label}与既有编码冲突")
        amount=split_amount(target.get("carryover"),"承接量")
        if amount<0: raise DomainError("SPLIT_INVALID","承接量不能为负")
        carryover[item]=amount;registry[item]=item
        if label: registry[label]=item
        entries.append({"item":item,"label":label or item,"carryover":str(amount)})
    declared=mapping.get("source_cumulative")
    declared=split_amount(declared,"旧码已审累计") if declared is not None else None
    return {"split_id":split_id.strip(),"source":source,"effective":effective,"targets":entries,"carryover":carryover,"registry":registry,"declared":declared,"unit":"t" if source=="001" else "m³"}
def validate_split_data(split,good):
    "拆分基期=旧码在生效周期前最后的已审累计；承接合计必须与基期对平，否则整批不切换。"
    candidates=[row for row in good if row["item"]==split["source"] and valid_period(row.get("period","")) and row["period"]<split["effective"]]
    if not candidates: raise DomainError("SPLIT_NO_BASELINE","拆分前旧码无已审累计，无法回溯来源")
    latest=max(candidates,key=lambda row:(row["period"],row.get("_line",0)))
    baseline=number(latest["cumulative_qty"])
    if split["declared"] is not None and split["declared"]!=baseline:
        raise DomainError("SPLIT_BASELINE_MISMATCH",f"映射声明旧码已审累计{split['declared']}与台账记录{baseline}不符")
    total=sum(split["carryover"].values(),Decimal(0))
    if total!=baseline: raise DomainError("SPLIT_UNBALANCED",f"承接合计{total}与旧码已审累计{baseline}不符，同一段工程量不能算两次")
    split["baseline"]=baseline
def apply_split(split,good,bad):
    "生效起旧码停用、新码标注旧码来源；不满足生效条件的行隔离。"
    out=[];retired=mapped=0
    for row in good:
        item=row["item"];period=row.get("period","")
        if item==split["source"] and valid_period(period) and period>=split["effective"]:
            bad.append(reject(row,"CODE_RETIRED",f"旧码{split['source']}已于{split['effective']}拆分为新码，继续申报会重复计量"));retired+=1;continue
        if item in split["carryover"]:
            if not valid_period(period) or period<split["effective"]:
                bad.append(reject(row,"SPLIT_NOT_EFFECTIVE",f"新码{item}自{split['effective']}起承接旧码{split['source']}"));continue
            row={**row,"source_item":split["source"],"split_id":split["split_id"],"split_base":str(split["carryover"][item]),"unit":split["unit"]};mapped+=1
        out.append(row)
    return out,bad,retired,mapped
def evaluate(rows,context):
    parameters=context.get("parameters",{}) if isinstance(context,dict) else {}
    mapping=parameters.get("split_mapping")
    split=prepare_split(mapping) if mapping is not None else None
    registry={**ITEMS,**(split["registry"] if split else {})}
    good=[];bad=[]
    for row in rows:
        try:
            item=registry.get(row.get("item"))
            if item is None:raise DomainError("UNKNOWN_ITEM","清单项未登记")
            current=number(row["cumulative_qty"]);previous=number(row["previous_qty"]);reported=number(row["reported"])
            if current<0 or previous<0:raise DomainError("NEGATIVE_CUMULATIVE","累计量不能为负")
            good.append({**row,"item":item,"cumulative_qty":str(current),"previous_qty":str(previous),"reported":str(reported),"unit":"t" if item=="001" else "m³"})
        except (DomainError,KeyError) as e:bad.append(reject(row,getattr(e,"code","MISSING_FIELD"),str(e)))
    metrics={"accepted":len(good),"items":len(set(r["item"] for r in good))}
    if split:
        validate_split_data(split,good)
        good,bad,retired,mapped=apply_split(split,good,bad)
        metrics.update(accepted=len(good),items=len(set(r["item"] for r in good)))
        metrics["split"]={"split_id":split["split_id"],"source_item":split["source"],"effective":split["effective"],"baseline":str(split["baseline"]),"carryover_total":str(sum(split["carryover"].values(),Decimal(0))),"targets":split["targets"],"mapped":mapped,"retired":retired,"balanced":True}
    return {"rows":good,"quarantine":bad,"metrics":metrics}
