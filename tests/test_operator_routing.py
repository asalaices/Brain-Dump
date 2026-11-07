# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Packaged operator routing/profile tests with independent synthetic Git roots."""
from pathlib import Path
import tempfile,json,subprocess,unittest
from unittest.mock import patch
from brain_bridge.operator import routing as b, managed as m

class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()/'repo';self.root.mkdir()
        b.git(self.root,'init','-q','-b','main');b.git(self.root,'config','user.name','Synthetic');b.git(self.root,'config','user.email','synthetic@example.invalid')
        (self.root/'README').write_text('synthetic');b.git(self.root,'add','.');b.git(self.root,'commit','-qm','fixture')
        b.git(self.root,'update-ref','refs/remotes/origin/main',b.git(self.root,'rev-parse','HEAD'))
        self.c={'schema_version':1,'cli':str(self.root/'bin/brain-bridge'),'identity_repo':str(self.root/'identity'),'source_repo':str(self.root/'source'),'source':'primary','cache_dir':str(self.root/'cache'),'minimum_version':'0.8.0'}

    def commit(self):
        b.git(self.root,'add','.');b.git(self.root,'commit','-qm','reviewed fixture');b.git(self.root,'update-ref','refs/remotes/origin/main',b.git(self.root,'rev-parse','HEAD'))

    def route(self,mode='paused',reader='managed',generation=1):
        file=self.root/b.CONTROL_PATH;file.parent.mkdir(exist_ok=True);file.write_text(json.dumps({'schema_version':2,'mode':mode,'reader':reader,'generation':generation}));self.commit()

    def test_uncommitted_policy_and_profile_do_not_activate(self):
        self.route('legacy','legacy',0);file=self.root/b.CONTROL_PATH;file.write_text(json.dumps({'schema_version':2,'mode':'managed','reader':'managed','generation':1}))
        (self.root/m.PROFILE_PATH).write_text(json.dumps(self.c))
        self.assertEqual(b.publisher_route(self.root)['mode'],'legacy')
        committed=b.control_json(self.root,'origin/main',m.PROFILE_PATH)
        with patch.object(m.subprocess,'run') as runtime:
            with self.assertRaisesRegex(ValueError,'committed'):m.profile(self.root,lambda *args:committed)
            runtime.assert_not_called()

    def test_old_runtime_and_unknown_profile_fail_closed(self):
        (self.root/'.brain-bridge').mkdir();(self.root/m.PROFILE_PATH).write_text(json.dumps(self.c));self.commit()
        committed=b.control_json(self.root,'origin/main',m.PROFILE_PATH)
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'brain-bridge 0.3.0','')):
            with self.assertRaisesRegex(ValueError,'unsupported'):m.profile(self.root,lambda *args:committed)
        self.c['arbitrary_arguments']=['--unsafe'];(self.root/m.PROFILE_PATH).write_text(json.dumps(self.c));self.commit()
        with self.assertRaisesRegex(ValueError,'invalid'):m.profile(self.root,b.control_json)

    def test_unknown_future_runtime_is_not_assumed_compatible(self):
        (self.root/'.brain-bridge').mkdir();(self.root/m.PROFILE_PATH).write_text(json.dumps(self.c));self.commit()
        committed=b.control_json(self.root,'origin/main',m.PROFILE_PATH)
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'brain-bridge 9.0.0','')):
            with self.assertRaisesRegex(ValueError,'unsupported'):m.profile(self.root,lambda *args:committed)

    def test_operational_route_refreshes_stale_local_reader_selection(self):
        self.route('legacy','legacy',0);old=b.git(self.root,'rev-parse','HEAD')
        remote=self.root.parent/'reader-remote.git';b.run('git','clone','--bare',str(self.root),str(remote));b.git(self.root,'remote','add','origin',str(remote))
        self.route('paused','managed',1);b.git(self.root,'push','origin','main');b.git(self.root,'update-ref','refs/remotes/origin/main',old)
        self.assertEqual(b.reader_route(b.publisher_route(self.root)),'legacy')
        self.assertEqual(b.reader_route(b.refresh_publisher_route(self.root)),'managed')

    def test_each_framework_invocation_rejects_runtime_replacement(self):
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'brain-bridge 0.3.0','')) as command:
            with self.assertRaisesRegex(ValueError,'unsupported'):m.invoke(self.c,'export','--source','primary')
            command.assert_called_once_with([self.c['cli'],'--version'],capture_output=True,text=True,timeout=30)

    def test_fresh_committed_generation_or_profile_change_blocks_promotion(self):
        self.route('managed','managed',2)
        profile=self.root/m.PROFILE_PATH;profile.write_text(json.dumps(self.c));self.commit()
        remote=self.root.parent/'remote.git';b.run('git','clone','--bare',str(self.root),str(remote));b.git(self.root,'remote','add','origin',str(remote))
        initial=b.publisher_route(self.root)
        self.c['cache_dir']='/synthetic/different-cache';profile.write_text(json.dumps(self.c));self.commit();b.git(self.root,'push','origin','main')
        with self.assertRaisesRegex(ValueError,'profile changed'):b.require_managed_promotion_route(self.root,initial)
        initial=b.publisher_route(self.root)
        self.route('paused','managed',3);b.git(self.root,'push','origin','main')
        with self.assertRaisesRegex(ValueError,'changed or paused'):b.require_managed_promotion_route(self.root,initial)

    def test_managed_create_requires_external_output_and_delegates_stable_input(self):
        with self.assertRaisesRegex(ValueError,'--output'):m.create(self.c,'entry.json',None)
        with patch.object(m,'named',return_value={'status':'plan'}) as call:
            self.assertEqual(m.create(self.c,'entry.json','/external/draft.json')['status'],'plan')
            call.assert_called_once_with(self.c,'create','--entry','entry.json','--output','/external/draft.json')
