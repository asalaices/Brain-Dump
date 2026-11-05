# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Provider adapters preserve native identity/results and never trigger work."""
import json
import base64
import unittest
from unittest.mock import patch
from brain_bridge.connectors import observe,load_connector,ConnectorError,NoRedirect
from brain_bridge.policy import AccessDenied

IDENTITY={'schema_version':1,'instance_uuid':'11111111-1111-4111-8111-111111111111','github_repository_id':'123'}
class Fake:
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def cli_json(self,tool,host,endpoint):self.calls.append((tool,host,endpoint));return self.responses[endpoint]
    def jenkins_json(self,url,user,token):self.calls.append((url,user,token));return self.responses[url]

class ConnectorTests(unittest.TestCase):
    def test_github_records_observed_pending_not_success(self):
        spec={'provider':'github_actions','repository':'example/code','repository_id':'123'}
        transport=Fake({'repos/example/code':{'id':123,'permissions':{'pull':True}},'repos/example/code/actions/runs/9':{'id':9,'run_attempt':2,'name':'Synthetic workflow','head_sha':'a'*40,'status':'queued','conclusion':None,'html_url':'https://github.com/example/code/actions/runs/9'}})
        result=observe(spec,'9',transport)
        self.assertEqual(result['status'],'queued');self.assertIsNone(result['conclusion']);self.assertEqual(result['run_attempt'],'2')
        self.assertEqual(len(transport.calls),2)
    def test_github_wrong_repository_blocks_run_request(self):
        transport=Fake({'repos/example/code':{'id':999,'permissions':{'pull':True}}})
        with self.assertRaises(AccessDenied):observe({'provider':'github_actions','repository':'example/code','repository_id':'123'},'9',transport)
        self.assertEqual(len(transport.calls),1)
    def test_gitlab_preserves_nested_namespace_and_native_failure(self):
        transport=Fake({'projects/55':{'id':55,'path_with_namespace':'group/subgroup/project'},'projects/55/pipelines/9':{'id':9,'project_id':55,'sha':'b'*40,'status':'failed','web_url':'https://gitlab.example/group/subgroup/project/-/pipelines/9'}})
        result=observe({'provider':'gitlab','host':'gitlab.example','project_id':'55'},'9',transport)
        self.assertEqual(result['project_path'],'group/subgroup/project');self.assertEqual(result['status'],'failed')
        self.assertTrue(all(call[0]=='glab' for call in transport.calls))
    def test_gitlab_response_cannot_change_project_identity(self):
        transport=Fake({'projects/55':{'id':55},'projects/55/pipelines/9':{'id':9,'project_id':999}})
        with self.assertRaises(ConnectorError):observe({'provider':'gitlab','host':'gitlab.example','project_id':'55'},'9',transport)
    def test_jenkins_binds_numbered_build_and_observed_result(self):
        spec={'provider':'jenkins','job_url':'https://ci.example/job/folder/job/project/','username_env':'TEST_JENKINS_USER','token_env':'TEST_JENKINS_TOKEN'}
        url=spec['job_url']+'7/'
        transport=Fake({url+'api/json':{'number':7,'url':url,'building':False,'result':'UNSTABLE'}})
        result=observe(spec,'7',transport)
        self.assertEqual(result['result'],'UNSTABLE');self.assertEqual(result['build_url'],url)
        self.assertEqual(transport.calls[0][1:],(spec['username_env'],spec['token_env']))
    def test_jenkins_wrong_build_is_rejected(self):
        spec={'provider':'jenkins','job_url':'https://ci.example/job/project/','username_env':'U','token_env':'T'}
        transport=Fake({spec['job_url']+'7/api/json':{'number':8,'url':spec['job_url']+'8/','building':False,'result':'SUCCESS'}})
        with self.assertRaises(ConnectorError):observe(spec,'7',transport)
    def test_invalid_run_id_is_not_sent_to_provider(self):
        for value in ['../secret',0,True,'0','-1']:
            transport=Fake({})
            with self.assertRaises(ConnectorError):observe({'provider':'gitlab'},value,transport)
            self.assertEqual(transport.calls,[])
    def test_redirects_are_rejected_before_credentials_can_follow(self):
        with self.assertRaises(ConnectorError):NoRedirect().redirect_request(None,None,None,None,None,None)

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.config={'schema_version':1,'connectors':[{'name':'ci','provider':'gitlab','host':'gitlab.example','project_id':'55'}]}
    def git(self,repo,*args):
        if args==('remote','get-url','origin'):return 'https://github.com/example/code.git'
        if args==('show','HEAD:.brain-bridge/identity.json'):return json.dumps(IDENTITY)
        if args==('show','HEAD:.brain-bridge/connectors.json'):return json.dumps(self.config)
        raise AssertionError(args)
    def load(self,name='ci'):
        config=self.config
        class API:
            def api(self,endpoint):
                if endpoint=='repos/example/code':return {'id':123}
                if endpoint=='repos/example/code/commits/main':return {'sha':'c'*40}
                obj=IDENTITY if '/identity.json?' in endpoint else config
                return {'type':'file','encoding':'base64','content':base64.b64encode(json.dumps(obj).encode()).decode()}
        with patch('brain_bridge.authority.git',side_effect=self.git):return load_connector('code',name,API())
    def test_only_committed_named_connectors_are_selected(self):
        self.assertEqual(self.load()['project_id'],'55')
        with self.assertRaises(AccessDenied):self.load('unregistered')
    def test_github_evidence_registry_uses_verified_registration_context(self):
        self.config['connectors']=[{'name':'ci','provider':'github','repository':'example/code','repository_id':'123'}]
        self.assertEqual(self.load()['provider'],'github')
        self.config['connectors'][0]['repository_id']='0123'
        with self.assertRaises(AccessDenied):self.load()

    def test_duplicate_and_unknown_config_fields_deny(self):
        self.config['connectors'].append(dict(self.config['connectors'][0]))
        with self.assertRaises(AccessDenied):self.load()
        self.config['connectors']=self.config['connectors'][:1];self.config['connectors'][0]['token']='never-a-config-secret'
        with self.assertRaises(AccessDenied):self.load()

if __name__=='__main__':unittest.main()
