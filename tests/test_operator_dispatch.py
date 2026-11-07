# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Operator command boundaries; no private project, runtime or provider needed."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from brain_bridge import operator as op
from brain_bridge.__main__ import main, parser

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.state={'mode':'managed','reader':'managed','generation':2}
        self.c={'source':'independent-source','cli':'/synthetic/brain-bridge'}
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.root=self.stack.enter_context(patch.object(op,'project_root',return_value=Path('/synthetic/project')))
        self.route=self.stack.enter_context(patch.object(op,'refresh_publisher_route',return_value=self.state))
        self.profile=self.stack.enter_context(patch.object(op.managed,'profile',return_value=self.c))

    def test_paused_dump_preserves_original_without_loading_runtime(self):
        self.state['mode']='paused'
        result=op.dispatch('project','dump',record='/private/original.json',execute=True,yes=True)
        self.assertFalse(result['published']);self.assertTrue(result['retained'])
        self.profile.assert_not_called()

    def test_paused_create_is_rejected_before_runtime(self):
        self.state['mode']='paused'
        with self.assertRaisesRegex(ValueError,'paused'):op.dispatch('project','create',entry='entry',output='draft')
        self.profile.assert_not_called()

    def test_legacy_mode_cannot_fall_back(self):
        self.state.update(mode='legacy',reader='legacy')
        with self.assertRaisesRegex(ValueError,'no legacy fallback'):op.dispatch('project','latest')

    def test_sync_plans_without_reading_or_synchronizing_source(self):
        with patch.object(op.managed,'synchronize') as sync:
            self.assertFalse(op.dispatch('project','pull')['executed']);sync.assert_not_called()

    def test_create_preserves_exact_entry_output_and_execution_flags(self):
        with patch.object(op.managed,'create',return_value={'status':'plan'}) as create:
            op.dispatch('project','create',entry='/external/original-entry',output='/external/original-envelope')
            create.assert_called_once_with(self.c,'/external/original-entry','/external/original-envelope',False,False)

    def test_dump_delegates_normal_promoter_not_ordinary_publish_default(self):
        with patch.object(op.managed,'publish',return_value={'published':False}) as publish:
            op.dispatch('project','dump',record='/external/original',execute=True,yes=True)
            self.assertEqual(publish.call_args.args[:4],(Path('/synthetic/project'),'/external/original',self.c,self.state))
            self.assertEqual(publish.call_args.args[-2:],(True,True))

    def test_denied_read_is_not_replaced_with_local_result(self):
        with patch.object(op.managed,'read',side_effect=ValueError('denied')):
            with self.assertRaisesRegex(ValueError,'denied'):op.dispatch('project','export')

    def test_bad_operation_options_are_rejected_before_git(self):
        for operation,options in [('create',{'execute':True}),('status',{'record':'file'}),('profile',{'execute':True,'yes':True}),('dump',{'output':'file'})]:
            with self.subTest(operation=operation,options=options),self.assertRaises(ValueError):
                op.dispatch('project',operation,**options)
        self.root.assert_not_called()

    def test_missing_route_is_not_a_legacy_default(self):
        from brain_bridge.operator import routing
        with patch.object(routing,'control_json',return_value=(None,'a'*40)):
            with self.assertRaisesRegex(ValueError,'explicitly committed'):routing.publisher_route('/synthetic')

    def test_operator_pending_json_is_nonzero_and_pretty_equivalent(self):
        results=[]
        for flags in [[],['--json'],['--pretty']]:
            out=io.StringIO()
            with patch('brain_bridge.__main__.operator_dispatch',return_value={'ok':False,'status':'pending','published':False}),contextlib.redirect_stdout(out):
                self.assertEqual(main(['operator','--project-repo','independent','dump','--record','original',*flags]),1)
            results.append(json.loads(out.getvalue()))
        self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2])

    def test_standard_publisher_remains_separate_and_plan_by_default(self):
        args=parser().parse_args(['publish','--identity-repo','identity','--repo','source','--record','record'])
        self.assertFalse(args.execute)
        out=io.StringIO()
        with patch('brain_bridge.__main__.propose_record',return_value={'status':'plan'}) as publish,patch('brain_bridge.__main__.operator_dispatch',side_effect=AssertionError('operator called')),contextlib.redirect_stdout(out):
            self.assertEqual(main(['publish','--identity-repo','identity','--repo','source','--record','record']),0)
        publish.assert_called_once_with('identity','source','record',False,False)
