"""Current full behavioral inventories, new receipts only; no account I/O."""
import argparse
from record_00405 import run

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group',choices=('python','node','independent'))
    parser.add_argument('output')
    args=parser.parse_args()
    raise SystemExit(run(args.group,args.output,task='005'))
