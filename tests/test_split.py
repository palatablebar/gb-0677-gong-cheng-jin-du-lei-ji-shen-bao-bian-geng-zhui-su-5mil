import pytest
from app.pipeline import calculate,execute,load_sample,sample_parameters
from app.modules.m2_billitems.rules import evaluate as m2
from app.modules.m4_increment.rules import evaluate as m4
from app.errors import DomainError
from app import store
def mapping(**kw):
    base={"split_id":"SPLIT-2026-10","source_item":"001","effective":"2026-10","targets":[{"item":"001-S","label":"结构","carryover":"135"},{"item":"001-F","label":"基础","carryover":"90"}]}
    base.update(kw);return base
def ctx(mp=None): return {"parameters":{"split_mapping":mp if mp is not None else mapping()}}
def source_row(period="2026-09",cumulative="225"): return {"claim_id":"A1","item":"001","period":period,"cumulative_qty":cumulative,"previous_qty":"200","reported":"0"}
def target_row(item="001-S",period="2026-10",cumulative="150",claim="A2"): return {"claim_id":claim,"item":item,"period":period,"cumulative_qty":cumulative,"previous_qty":"0","reported":"0"}
@pytest.fixture
def split_run(): return calculate(load_sample("split.csv"),sample_parameters("split.csv"))
def test_split_mapping_traceable(split_run):
    split=split_run["stages"][1]["metrics"]["split"]
    assert split["source_item"]=="001" and split["baseline"]=="225" and split["carryover_total"]=="225" and split["balanced"] is True
    assert {t["item"] for t in split["targets"]}=={"001-S","001-F"} and split["retired"]==1 and split["mapped"]==4
def test_split_rows_carry_lineage(split_run):
    rows=[r for r in split_run["stages"][5]["rows"] if r.get("split_id")]
    assert rows and all(r["source_item"]=="001" and r["split_id"]=="SPLIT-2026-10" and r["split_base"] in {"135","90"} for r in rows)
    assert {r["item"] for r in rows}=={"001-S","001-F"}
def test_retired_old_code_not_double_counted(split_run):
    retired=[r for r in split_run["stages"][1]["quarantine"] if r["reason"]=="CODE_RETIRED"]
    assert len(retired)==1 and retired[0]["claim_id"]=="S0005"
    assert all(r.get("claim_id")!="S0005" for r in split_run["stages"][5]["rows"])
def test_first_period_previous_comes_from_carryover(split_run):
    rows={r["claim_id"]:r for r in split_run["stages"][3]["rows"]}
    assert rows["S0003"]["approved_previous"]=="135" and rows["S0003"]["increment_qty"]=="15" and rows["S0003"]["previous_source"]=="split_mapping"
    assert rows["S0004"]["approved_previous"]=="90" and rows["S0004"]["increment_qty"]=="5"
    assert rows["S0006"]["increment_qty"]=="15" and "previous_source" not in rows["S0006"]
def test_split_reconciliation_balances(split_run):
    m=split_run["stages"][5]["metrics"]
    assert m["balanced"] is True and m["differences"]==0
    split=m["split"]
    assert split["source_cumulative"]=="225" and split["carryover_total"]=="225" and split["carryover_balanced"] is True
    assert split["increment_total"]=="40" and split["expected_total"]=="3740.00"
    assert {t["item"] for t in split["targets"]}=={"001-S","001-F"}
def test_unbalanced_split_rejected():
    with pytest.raises(DomainError) as e:
        m2([source_row(),target_row()],ctx(mapping(targets=[{"item":"001-S","carryover":"136"},{"item":"001-F","carryover":"90"}])))
    assert e.value.code=="SPLIT_UNBALANCED"
def test_declared_baseline_mismatch():
    with pytest.raises(DomainError) as e: m2([source_row(),target_row()],ctx(mapping(source_cumulative="226")))
    assert e.value.code=="SPLIT_BASELINE_MISMATCH"
def test_no_baseline_no_switch():
    with pytest.raises(DomainError) as e: m2([source_row(period="2026-11"),target_row()],ctx())
    assert e.value.code=="SPLIT_NO_BASELINE"
def test_target_before_effective_quarantined():
    r=m2([source_row(),target_row(period="2026-09")],ctx())
    assert r["quarantine"][0]["reason"]=="SPLIT_NOT_EFFECTIVE"
def test_target_code_collision():
    with pytest.raises(DomainError) as e: m2([source_row()],ctx(mapping(targets=[{"item":"002","carryover":"225"}])))
    assert e.value.code=="SPLIT_INVALID"
def test_negative_carryover():
    with pytest.raises(DomainError) as e: m2([source_row()],ctx(mapping(targets=[{"item":"001-S","carryover":"-1"}])))
    assert e.value.code=="SPLIT_INVALID"
def test_duplicate_target():
    with pytest.raises(DomainError) as e: m2([source_row()],ctx(mapping(targets=[{"item":"001-S","carryover":"100"},{"item":"001-S","carryover":"125"}])))
    assert e.value.code=="SPLIT_INVALID"
def test_bad_effective_and_shape():
    with pytest.raises(DomainError): m2([source_row()],ctx(mapping(effective="202610")))
    with pytest.raises(DomainError): m2([source_row()],ctx("not-a-mapping"))
def test_new_code_unknown_without_mapping():
    r=m2([target_row()],{"parameters":{}})
    assert r["quarantine"][0]["reason"]=="UNKNOWN_ITEM"
def test_previous_revisions_beat_carryover():
    rows=[{**target_row(),"split_base":"135","item":"001-S","unit_price":"100"}]
    r=m4(rows,{"parameters":{"previous_revisions":{"A2":"140"}}})
    assert r["rows"][0]["approved_previous"]=="140" and r["rows"][0]["increment_qty"]=="10"
def test_carryover_applied_once_per_item():
    rows=[{**target_row(claim="A2",period="2026-10",cumulative="150"),"split_base":"135","unit_price":"100"},{**target_row(claim="A3",period="2026-11",cumulative="165"),"split_base":"135","previous_qty":"150","unit_price":"100"}]
    out={r["claim_id"]:r for r in m4(rows,{"parameters":{}})["rows"]}
    assert out["A2"]["approved_previous"]=="135" and out["A3"]["approved_previous"]=="150"
def test_rerun_same_batch_not_duplicated(client):
    a=client.post("/api/runs",json={"sample":"split.csv"}).get_json()
    b=client.post("/api/runs",json={"sample":"split.csv"}).get_json()
    assert a["run_id"]==b["run_id"] and len(store.history())==1
    assert a["stages"][3]["rows"]==b["stages"][3]["rows"]
    assert a["stages"][6]["metrics"]["sha256"]==b["stages"][6]["metrics"]["sha256"]
def test_failed_switch_keeps_old_visa(client):
    first=client.post("/api/runs",json={"sample":"clean.csv"}).get_json()
    assert client.post(f"/api/runs/{first['run_id']}/review",json={"version":1,"decision":"已复核"}).status_code==200
    bad=mapping(targets=[{"item":"001-S","carryover":"136"},{"item":"001-F","carryover":"90"}])
    r=client.post("/api/runs",json={"csv":load_sample("split.csv").decode(),"parameters":{"split_mapping":bad}})
    assert r.status_code==422 and r.get_json()["code"]=="SPLIT_UNBALANCED"
    assert len(store.history())==1
    latest=store.latest()
    assert latest["run_id"]==first["run_id"] and latest["decision"]=="已复核" and latest["version"]==2
    assert client.get(f"/api/runs/{first['run_id']}/archive").status_code==200
def test_explicit_parameters_skip_split(client):
    p=client.post("/api/runs",json={"sample":"split.csv","parameters":{}}).get_json()
    assert "split" not in p["stages"][1]["metrics"]
    assert any(r["reason"]=="UNKNOWN_ITEM" for r in p["stages"][1]["quarantine"])
def test_archive_export_carries_split_lineage(client):
    p=client.post("/api/runs",json={"sample":"split.csv"}).get_json()
    body=client.get(f"/api/runs/{p['run_id']}/archive").data.decode("utf-8-sig")
    assert "SPLIT-2026-10" in body and "001-S" in body and "CODE_RETIRED" in body
def test_split_run_archive_ready(split_run):
    m=split_run["stages"][6]["metrics"]
    assert m["ready"] is True and m["differences"]==0
