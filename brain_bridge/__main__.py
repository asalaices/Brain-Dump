import argparse,json
from .store import json_search,rebuild,sqlite_search
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
elif args.backend=="json" or (args.backend=="auto" and not args.db):
    result=json_search(args.root,args.term)
else:
    if not args.db: parser.error("--db is required for sqlite")
    try:
        rebuild(args.root,args.db)
        result=sqlite_search(args.db,args.term)
    except (OSError,Exception):
        if args.backend=="sqlite":raise
        result=json_search(args.root,args.term)
print(json.dumps(result,ensure_ascii=False,indent=2))
