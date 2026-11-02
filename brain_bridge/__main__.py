import argparse,json
from .store import rebuild,search
from .sync import sync
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
g=sub.add_parser("sync",help="guarded fast-forward Git pull and SQLite refresh")
g.add_argument("--repo",required=True)
g.add_argument("--remote",required=True,help="exact expected origin URL")
g.add_argument("--branch",default="main")
g.add_argument("--records",default="records",help="records directory relative to repo")
g.add_argument("--db",required=True,help="SQLite path outside checkout")
args=parser.parse_args()
if args.action=="index": result={"indexed":rebuild(args.root,args.db)}
elif args.action=="sync": result=sync(args.repo,args.remote,args.branch,args.records,args.db)
else: result=search(args.root,args.term,args.backend,args.db)
print(json.dumps(result,ensure_ascii=False,indent=2))
