# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Graph output preserves evidence and never invents completed tasks."""
import json
import unittest
from pathlib import Path
from brain_bridge.graphs import evidence_graph,render_dot,render_mermaid
class GraphTests(unittest.TestCase):
    def setUp(self):
        self.doc=json.loads((Path(__file__).resolve().parents[1]/'schemas/record.v3.synthetic.json').read_text())
        self.items=[('synthetic.json','a'*64,self.doc)]
    def test_record_baseline_is_an_explicit_unresolved_edge(self):
        graph=evidence_graph(self.items,'123')
        self.assertTrue(any(n.get('unresolved') for n in graph['nodes']))
        self.assertTrue(any(e['relation']=='covers_since' for e in graph['edges']))
        self.assertEqual(graph,evidence_graph(self.items,'123'))
    def test_task_states_come_only_from_snapshot(self):
        tasks={'project_id':'synthetic-project','revision':7,'items':[{'id':'one','label':'BD1','title':'Work','status':'WIP','depends':['missing']}]}
        graph=evidence_graph(self.items,'123',tasks)
        self.assertEqual(graph['unresolved_tasks'],['missing'])
        self.assertEqual([n['status'] for n in graph['nodes'] if n.get('task_id')=='one'],['WIP'])
    def test_task_cycles_are_reported_not_silently_satisfied(self):
        tasks={'project_id':'project','revision':1,'items':[{'id':'a','status':'Open','depends':['b']},{'id':'b','status':'Open','depends':['a']}]}
        self.assertTrue(evidence_graph(self.items,'123',tasks)['task_cycles'])
    def test_unknown_task_status_rejected(self):
        with self.assertRaises(ValueError):evidence_graph(self.items,'123',{'project_id':'p','revision':1,'items':[{'id':'a','status':'probably done'}]})
    def test_large_dependency_chain_does_not_recurse(self):
        tasks={'project_id':'p','revision':1,'items':[{'id':str(i),'status':'Open','depends':[str(i+1)] if i<1499 else []} for i in range(1500)]}
        graph=evidence_graph(self.items,'123',tasks)
        self.assertEqual(graph['task_cycles'],[]);self.assertEqual(graph['unresolved_tasks'],[])

    def test_renderers_do_not_accept_label_injection(self):
        self.doc['entry']['title']='x"]\n%%{init: {}}%%<script>alert(1)</script>'
        graph=evidence_graph(self.items,'123');mermaid=render_mermaid(graph)
        self.assertNotIn('<script>',mermaid)
        self.assertNotIn('\n%%',mermaid)
        self.assertIn('digraph brain_bridge',render_dot(graph))

if __name__=='__main__':unittest.main()
