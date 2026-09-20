"""Rerun the score-ordered compatible parent-layout control on a shared context."""
import argparse,csv,json
from pathlib import Path
from package_paths import ROOT,CODE
import run_l1_control as control
import run_rq2_matched_budget as matched

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',default='C019');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False)
 # The original control uses R/matrix_c/raw_cases. A small directory adapter
 # resolves that lookup into the package without copying the candidate archive.
 class ContextRoot:
  def __truediv__(self,s):
   if s=='matrix_c/raw_cases':return ROOT/'data/comparison_contexts'
   raise ValueError(s)
 control.R=ContextRoot();control.HERE=a.output
 matched.PROTOCOL_DIR=CODE/'inputs'
 print(control.case(a.case))
 got=json.loads((a.output/'l1/raw_cases'/a.case/'outcome.json').read_text('utf-8'))
 rows=list(csv.DictReader((ROOT/'data/evaluation/controls/l1/results.csv').open(encoding='utf-8')));old=next(r for r in rows if r['case_id']==a.case)
 for field in ['achieved_count','completed','root_coverage_qcov','l1_layout_crossing_count']:
  if abs(float(got[field])-float(old[field]))>1e-10:raise RuntimeError(f'Archive differs: {field}')
 print('Archived parent-layout control reproduced.')

if __name__=='__main__':main()
