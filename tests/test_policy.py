# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Synthetic negative authorization tests; no credentials or private records."""
import base64
import json
import unittest
from unittest.mock import patch
from brain_bridge.policy import Identity, Policy, AccessDenied
from brain_bridge.authority import GitHubAuthority, Grant, github_slug

IDENTITY={"schema_version":1,"instance_uuid":"11111111-1111-4111-8111-111111111111","github_repository_id":"123"}
KEY=IDENTITY['instance_uuid']+'-123'
def policy(read=(),write=()):
    return {"schema_version":1,"default_policy":"deny","reader_allow":list(read),"writer_allow":list(write)}

class PolicyTests(unittest.TestCase):
    def setUp(self):self.identity=Identity.parse(json.dumps(IDENTITY))
    def test_reader_and_writer_do_not_imply_each_other(self):
        for reader,writer in [(False,False),(True,False),(False,True),(True,True)]:
            p=Policy.parse(json.dumps(policy([KEY] if reader else [],[KEY] if writer else [])))
            for op,allowed in [('read',reader),('write',writer)]:
                if allowed:p.require(self.identity,op)
                else:
                    with self.assertRaises(AccessDenied):p.require(self.identity,op)
    def test_malformed_and_unknown_policies_deny(self):
        for bad in [None,[],{},dict(policy(),extra=True),dict(policy(),schema_version=True),dict(policy(),schema_version=2),dict(policy(),default_policy='allow'),dict(policy(),reader_allow=['*']),dict(policy(),writer_allow=[KEY,KEY]),dict(policy(),reader_allow='all')]:
            with self.subTest(bad=bad),self.assertRaises(AccessDenied):Policy.parse(json.dumps(bad))
    def test_duplicate_json_keys_deny(self):
        with self.assertRaises(AccessDenied):Policy.parse('{"schema_version":1,"schema_version":1}')
    def test_copied_fork_identity_denied(self):
        with self.assertRaises(AccessDenied):self.identity.verify_repository(456)
    def test_noncanonical_identity_denied(self):
        for update in [{'github_repository_id':'0123'},{'github_repository_id':123},{'instance_uuid':'00000000-0000-0000-0000-000000000000'},{'schema_version':True}]:
            with self.assertRaises(AccessDenied):Identity.parse(json.dumps(dict(IDENTITY,**update)))
    def test_cache_names_bind_identity_source_and_policy_commit(self):
        g=Grant(KEY,'44','example/data','a'*40,'main')
        self.assertNotEqual(g.cache_key,Grant(KEY,'45','example/data','a'*40,'main').cache_key)
        self.assertNotEqual(g.cache_key,Grant(KEY,'44','example/data','b'*40,'main').cache_key)
    def test_unchanged_policy_reuses_namespace_across_record_commits(self):
        first=Grant(KEY,'44','example/data','a'*40,'main','c'*64)
        second=Grant(KEY,'44','example/data','b'*40,'main','c'*64)
        self.assertEqual(first.cache_key,second.cache_key)
        revoked=Grant(KEY,'44','example/data','b'*40,'main','d'*64)
        self.assertNotEqual(first.cache_key,revoked.cache_key)

    def test_origin_slug_parsing(self):
        for url in ['git@github.com:example/code.git','https://github.com/example/code.git','https://github.com/example/code']:
            self.assertEqual('example/code',github_slug(url))
        for url in ['https://github.com/../../code','https://github.com/../..','https://evil.invalid/example/code.git','-bad']:
            with self.assertRaises(AccessDenied):github_slug(url)

class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.code_id=123;self.source_id=456;self.can_pull=True;self.can_push=True;self.grants=policy([KEY],[KEY]);self.calls=[];self.registry_id="456";self.private=True
    def api(self,endpoint):
        self.calls.append(endpoint)
        if endpoint=='repos/example/code':return {'id':self.code_id}
        if endpoint=='repos/example/code/commits/main':return {'sha':'c'*40}
        if endpoint.startswith('repos/example/code/contents/'):
            obj=IDENTITY if '/identity.json?' in endpoint else {'schema_version':1,'sources':[{'name':'synthetic','github_repository':'example/data','github_repository_id':self.registry_id,'branch':'main'}]}
            return {'type':'file','encoding':'base64','content':base64.b64encode(json.dumps(obj).encode()).decode()}

        if endpoint=='repos/example/data':return {'id':self.source_id,'private':self.private,'permissions':{'pull':self.can_pull,'push':self.can_push}}
        if endpoint=='repos/example/data/commits/main':return {'sha':'a'*40}
        if endpoint=='repos/example/data/contents/.brain-bridge/trust.json?ref='+'a'*40:
            return {'encoding':'base64','type':'file','content':base64.b64encode(json.dumps(self.grants).encode()).decode()}
        raise AssertionError(endpoint)
    def git(self,repo,*args):
        if args==('remote','get-url','origin'):return 'git@github.com:example/'+('code' if str(repo)=='code' else 'data')+'.git'
        if args==('show','HEAD:.brain-bridge/identity.json'):return json.dumps(IDENTITY)
        if args==('show','HEAD:.brain-bridge/sources.json'):return json.dumps({'schema_version':1,'sources':[{'name':'synthetic','github_repository':'example/data','github_repository_id':self.registry_id,'branch':'main'}]})
        raise AssertionError(args)
    def snapshot(self,operation='read'):
        with patch('brain_bridge.authority.git',side_effect=self.git),patch.object(GitHubAuthority,'api',side_effect=self.api):
            return GitHubAuthority().snapshot('code','data',operation)
    def test_policy_is_requested_at_exact_authenticated_head(self):
        grant=self.snapshot();self.assertEqual(grant.commit,'a'*40)
        self.assertIn('repos/example/data/contents/.brain-bridge/trust.json?ref='+'a'*40,self.calls)
    def test_local_proposed_identity_and_registry_are_not_authority(self):
        original=self.git
        def no_local_documents(repo,*args):
            if args[0]=='show':raise AssertionError('Working or branch config must never authorize access')
            return original(repo,*args)
        with patch('brain_bridge.authority.git',side_effect=no_local_documents),patch.object(GitHubAuthority,'api',side_effect=self.api):
            grant=GitHubAuthority().snapshot('code','data')
        self.assertEqual(grant.identity_key,KEY)
    def test_source_repository_id_mismatch_denied_before_policy_read(self):
        self.registry_id='999'
        with self.assertRaises(AccessDenied):self.snapshot()
        self.assertFalse(any(call.startswith('repos/example/data/contents/') for call in self.calls))
    def test_repository_permission_is_required_even_with_policy_grant(self):
        self.can_pull=False
        with self.assertRaises(AccessDenied):self.snapshot()
    def test_public_destination_cannot_receive_operational_records(self):
        self.private=False
        with self.assertRaises(AccessDenied):self.snapshot('write')
        self.snapshot('read')
    def test_writer_needs_actual_github_push_permission(self):
        self.can_push=False
        with self.assertRaises(AccessDenied):self.snapshot('write')
    def test_fork_mismatch_prevents_policy_read(self):
        self.code_id=999
        with self.assertRaises(AccessDenied):self.snapshot()
        self.assertFalse(any(call.startswith('repos/example/data') for call in self.calls))
    def test_revocation_is_refreshed_on_every_request(self):
        self.snapshot();self.grants=policy()
        with self.assertRaises(AccessDenied):self.snapshot()
    def test_unavailable_upstream_has_no_cached_allow_fallback(self):
        self.snapshot()
        with patch('brain_bridge.authority.git',side_effect=self.git),patch.object(GitHubAuthority,'api',side_effect=AccessDenied('offline')):
            with self.assertRaises(AccessDenied):GitHubAuthority().snapshot('code','data')

if __name__=='__main__':unittest.main()
