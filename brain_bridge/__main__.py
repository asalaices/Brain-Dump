import argparse,json
from .store import json_search,rebuild,search
parser=argparse.ArgumentParser()
sub=parser.add_subparsers(dest="action",required=True)
s=sub.add_parser("search")
s.add_argument("--root",required=True)
s.add_argument("--term",required=True)
s.add_argument("--backend",choices=["json","sqlite","auto"],default="auto")
s.add_argument("--db")
i=sub.add_parser("index")
i.add_argument("--root",required=True)
i.add_argument("--db",required=True)
args=parser.parse_args()
if args.action=="index": result={"indexed":rebuild(args.root,args.db)}
else: result=search(args.root,args.term,args.backend,args.db)
print(json.dumps(result,ensure_ascii=False,indent=2))
