from pathlib import Path
import os
ROOT=Path(__file__).resolve().parent.parent
DATA_DIR=Path(os.environ.get("DATA_DIR", "/tmp/progressclaim"))
TITLE='工程进度累计申报与变更追溯'
SHORT='progressclaim'
COLUMNS=['claim_id', 'item', 'period', 'cumulative_qty', 'previous_qty', 'change_id', 'reversal', 'reported', 'note']
MODULES=[('claims', '申报采信'), ('billitems', '清单映射'), ('changes', '变更定版'), ('increment', '累计还原'), ('deductions', '扣回核算'), ('valuation', '进度对账'), ('certificates', '签证归档')]
RULE_VERSION="2026.11.18-r1"
SAMPLE_PARAMETERS={"split.csv":{"split_mapping":{"split_id":"SPLIT-2026-10","source_item":"001","effective":"2026-10","source_cumulative":"225","targets":[{"item":"001-S","label":"结构","carryover":"135"},{"item":"001-F","label":"基础","carryover":"90"}]}}}
